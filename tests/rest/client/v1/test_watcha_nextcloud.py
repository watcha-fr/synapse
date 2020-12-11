import json
from mock import Mock

import synapse.rest.admin
from synapse.api.errors import SynapseError
from synapse.rest.client.v1 import login, room

from tests import unittest

def simple_async_mock(return_value=None, raises=None):
    # AsyncMock is not available in python3.5, this mimics part of its behaviour
    async def cb(*args, **kwargs):
        if raises:
            raise raises
        return return_value

    return Mock(side_effect=cb)

class WatchaRoomNextcloudMappingEventTestCase(unittest.HomeserverTestCase):
    servlets = [
        synapse.rest.admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.room_owner = self.register_user("room_owner", "test")
        self.room_owner_tok = self.login("room_owner", "test")

        self.room_id = self.helper.create_room_as(
            self.room_owner, tok=self.room_owner_tok
        )

        self.nextcloud_handler = hs.get_nextcloud_handler()
        self.nextcloud_handler.update_room_nextcloud_mapping = simple_async_mock()
        self.nextcloud_handler.delete_room_nextcloud_mapping = simple_async_mock()
        self.nextcloud_directory_url = (
            "https://test/nextcloud/apps/files/?dir=/directory"
        )

    def send_room_nextcloud_mapping_event(self, request_content):
        request, channel = self.make_request(
            "PUT",
            "/rooms/{}/state/im.vector.web.settings".format(self.room_id),
            content=json.dumps(request_content),
            access_token=self.room_owner_tok,
        )
        self.render(request)

        return channel

    def test_create_new_room_nextcloud_mapping(self):
        channel = self.send_room_nextcloud_mapping_event(
            {"nextcloudShare": self.nextcloud_directory_url}
        )

        self.assertTrue(self.nextcloud_handler.update_room_nextcloud_mapping.called)
        self.assertEquals(200, channel.code)

    def test_delete_existing_room_nextcloud_mapping(self):
        self.send_room_nextcloud_mapping_event(
            {"nextcloudShare": self.nextcloud_directory_url}
        )
        channel = self.send_room_nextcloud_mapping_event({"nextcloudShare": ""})

        self.assertTrue(self.nextcloud_handler.delete_room_nextcloud_mapping.called)
        self.assertEquals(200, channel.code)

    def test_update_existing_room_nextcloud_mapping(self):
        self.send_room_nextcloud_mapping_event(
            {"nextcloudShare": self.nextcloud_directory_url}
        )
        channel = self.send_room_nextcloud_mapping_event(
            {"nextcloudShare": "https://test/nextcloud/apps/files/?dir=/directory2"}
        )

        self.assertTrue(self.nextcloud_handler.update_room_nextcloud_mapping.called)
        self.assertEquals(200, channel.code)

    def test_create_new_room_nextcloud_mapping_without_nextcloudShare_attribute(self):
        channel = self.send_room_nextcloud_mapping_event(
            {"nextcloud": self.nextcloud_directory_url}
        )

        self.assertFalse(self.nextcloud_handler.update_room_nextcloud_mapping.called)
        self.assertRaises(SynapseError)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            "VectorSetting is only used for Nextcloud integration.",
            json.loads(channel.result["body"])["error"],
        )

    def test_create_new_room_nextcloud_mapping_with_wrong_url(self):
        channel = self.send_room_nextcloud_mapping_event(
            {"nextcloudShare": "https://test/nextcloud/apps/files/?file=brandbook.pdf"}
        )

        self.assertFalse(self.nextcloud_handler.update_room_nextcloud_mapping.called)
        self.assertRaises(SynapseError)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            "The url doesn't point to a valid nextcloud directory path.",
            json.loads(channel.result["body"])["error"],
        )


class WatchaMembershipNextcloudSharingTestCase(unittest.HomeserverTestCase):
    """Tests that Nextcloud sharing is updated with membership event when the room is mapped with a Nextcloud directory"""

    servlets = [
        synapse.rest.admin.register_servlets_for_client_rest_resource,
        room.register_servlets,
        login.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.creator = self.register_user("creator", "pass")
        self.creator_tok = self.login("creator", "pass")

        self.inviter = self.register_user("inviter", "pass")
        self.inviter_tok = self.login("inviter", "pass")

        self.room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)

        # map a room with a Nextcloud directory :
        self.get_success(
            self.store.map_room_with_nextcloud_directory(self.room_id, "/directory", 1)
        )

        # mock some functions of WatchaRoomNextcloudMappingHandler
        self.nextcloud_handler = hs.get_nextcloud_handler()

        self.keycloak_client = self.nextcloud_handler.keycloak_client
        self.nextcloud_client = self.nextcloud_handler.nextcloud_client

        self.keycloak_client.get_user = simple_async_mock(
            return_value={"id": "1234", "username": "creator"},
        )
        self.nextcloud_client.add_user_to_group = simple_async_mock()
        self.nextcloud_client.remove_from_group = simple_async_mock()

    def test_update_nextcloud_share_on_invite_and_join_event(self):
        self.helper.invite(
            self.room_id, self.creator, self.inviter, tok=self.creator_tok
        )

        request, channel = self.make_request(
            "POST",
            "/_matrix/client/r0/rooms/{}/join".format(self.room_id),
            access_token=self.inviter_tok,
        )
        self.render(request)

        self.assertEquals(self.nextcloud_client.add_user_to_group.call_count, 2)
        self.assertEqual(200, channel.code)

    def test_update_nextcloud_share_on_leave_event(self):
        self.helper.invite(
            self.room_id, self.creator, self.inviter, tok=self.creator_tok
        )

        request, channel = self.make_request(
            "POST",
            "/_matrix/client/r0/rooms/{}/leave".format(self.room_id),
            access_token=self.inviter_tok,
        )
        self.render(request)

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_from_group.assert_called_once()
        self.assertEqual(200, channel.code)

    def test_update_nextcloud_share_on_kick_event(self):
        self.helper.invite(
            self.room_id, self.creator, self.inviter, tok=self.creator_tok
        )
        self.helper.join(self.room_id, user=self.inviter, tok=self.inviter_tok)

        request, channel = self.make_request(
            "POST",
            "/_matrix/client/r0/rooms/{}/kick".format(self.room_id),
            content={"user_id": self.inviter},
            access_token=self.inviter_tok,
        )
        self.render(request)

        self.assertEquals(self.nextcloud_client.add_user_to_group.call_count, 2)
        self.nextcloud_client.remove_from_group.assert_called_once()
        self.assertEqual(200, channel.code)

    def test_update_nextcloud_share_with_an_unmapped_room(self):
        self.nextcloud_handler.update_existing_nextcloud_share_for_user = (
            simple_async_mock()
        )

        room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)

        self.helper.invite(room_id, self.creator, self.inviter, tok=self.creator_tok)

        self.nextcloud_handler.update_existing_nextcloud_share_for_user.assert_not_called()


# +watcha
