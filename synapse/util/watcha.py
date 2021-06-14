from math import ceil, log2
from typing import Dict
import secrets
import string
import unicodedata

from synapse.api.constants import EventTypes, Membership
from synapse.push.presentable_names import descriptor_from_member_events
from synapse.types import StateMap


async def calculate_room_name(hs, room_id: str) -> str:
    """Get the name of a room if any, or calculate it from members' display names
    Inspired by https://github.com/matrix-org/synapse/blob/release-v1.33.0/synapse/push/presentable_names.py#L35

    Args:
        hs (synapse.server.HomeServer): server
        room_id: the id of the room
    """

    def _state_as_two_level_dict(state: StateMap[str]) -> Dict[str, Dict[str, str]]:
        ret = {}  # type: Dict[str, Dict[str, str]]
        for k, v in state.items():
            ret.setdefault(k[0], {})[k[1]] = v
        return ret

    store = hs.get_datastore()
    room_state_ids = await hs.get_state_handler().get_current_state_ids(room_id)
    if (EventTypes.Name, "") in room_state_ids:
        name_event = await store.get_event(room_state_ids[(EventTypes.Name, "")])
        room_name = name_event.content["name"]

        if room_name:
            return room_name

    all_members = []
    room_state_bytype_ids = _state_as_two_level_dict(room_state_ids)
    if EventTypes.Member in room_state_bytype_ids:
        member_events = await store.get_events(
            room_state_bytype_ids[EventTypes.Member].values()
        )
        all_members = [
            event
            for event in member_events.values()
            if event.content.get("membership") == Membership.JOIN
            or event.content.get("membership") == Membership.INVITE
        ]
        # Sort the member events oldest-first so the we name people in the
        # order the joined (it should at least be deterministic rather than
        # dictionary iteration order)
        all_members.sort(key=lambda e: e.origin_server_ts)

    return descriptor_from_member_events(all_members)


class Secrets:
    # https://fr.wikipedia.org/wiki/Ascii85#Version_ZeroMQ_(Z85)
    alphabet = string.ascii_letters + string.digits + ".-:+=^!/*?&<>()[]{}@%$#"
    min_entropy = 128

    def __init__(self, alphabet: str = None, min_entropy: int = None):
        if alphabet is not None:
            self.alphabet = unicodedata.normalize("NFKC", alphabet)

        if min_entropy is not None:
            self.min_entropy = min_entropy

    def gen_password(self) -> str:
        alphabet_length = len(self.alphabet)
        password_length = ceil(self.min_entropy / log2(alphabet_length))
        return "".join(secrets.choice(self.alphabet) for i in range(password_length))
