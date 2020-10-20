from .. import unittest
from mock import Mock
from requests import HTTPError

from synapse.api.errors import Codes, SynapseError


def simple_async_mock(return_value=None, raises=None):
    # AsyncMock is not available in python3.5, this mimics part of its behaviour
    async def cb(*args, **kwargs):
        if raises:
            raise raises
        return return_value

    return Mock(side_effect=cb)


class WatchaRoomNextcloudMappingTestCase(unittest.HomeserverTestCase):
    """ Tests the WatchaRoomNextcloudMappingHandler. """

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.handlers = hs.get_handlers().watcha_room_nextcloud_mapping_handler

        # Mock all functions which call Nextcloud API :
        self.handlers.get_keycloak_uid = simple_async_mock(return_value="keycloak_id")
        self.handlers.get_keycloak_access_token = simple_async_mock(return_value="tok")
        self.handlers.nextcloud_room_group_exists = simple_async_mock(
            return_value=False
        )
        self.handlers.create_nextcloud_group = simple_async_mock()
        self.handlers.create_new_nextcloud_share = simple_async_mock()
        self.handlers.delete_existing_nextcloud_share = simple_async_mock()
        self.handlers.delete_nextcloud_group = simple_async_mock()

    def test_set_new_room_nextcloud_mapping(self):
        self.get_success(
            self.handlers.update_nextcloud_mapping("room1", "@user1:test", "/directory")
        )

        mapped_directory = self.get_success(
            self.store.get_nextcloud_directory_path_from_roomID("room1")
        )

        self.assertEqual(mapped_directory, "/directory")

    def test_update_existing_room_nextcloud_mapping(self):
        self.get_success(
            self.store.set_room_mapping_with_nextcloud_directory("room1", "/directory")
        )
        old_mapped_directory = self.get_success(
            self.store.get_nextcloud_directory_path_from_roomID("room1")
        )

        self.assertEqual(old_mapped_directory, "/directory")
        self.get_success(
            self.handlers.update_nextcloud_mapping(
                "room1", "@user1:test", "/directory2"
            )
        )

        mapped_directory = self.get_success(
            self.store.get_nextcloud_directory_path_from_roomID("room1")
        )

        self.assertEqual(mapped_directory, "/directory2")

    def test_delete_existing_room_nextcloud_mapping(self):
        self.get_success(
            self.store.set_room_mapping_with_nextcloud_directory("room1", "/directory")
        )
        self.get_success(
            self.handlers.delete_room_mapping_with_nextcloud_directory("room1")
        )
        mapped_directory = self.get_success(
            self.store.get_nextcloud_directory_path_from_roomID("room1")
        )

        self.assertIsNone(mapped_directory)

    def test_set_new_room_nextcloud_mapping_without_access_token(self):
        self.handlers.get_keycloak_access_token = simple_async_mock(raises=HTTPError)
        error = self.get_failure(
            self.handlers.update_nextcloud_mapping(
                "room1", "@user1:test", "/directory"
            ),
            SynapseError,
        )

        self.assertEqual(error.value.code, 400)
        self.assertEqual(error.value.errcode, Codes.KEYCLOAK_CAN_NOT_GET_ACCESS_TOKEN)

    def test_set_new_room_nextcloud_mapping_without_keycloak_uid(self):
        self.handlers.get_keycloak_uid = simple_async_mock(raises=HTTPError())
        error = self.get_failure(
            self.handlers.update_nextcloud_mapping(
                "room1", "@user1:test", "/directory"
            ),
            SynapseError,
        )

        self.assertEqual(error.value.code, 400)
        self.assertEqual(error.value.errcode, Codes.KEYCLOAK_CAN_NOT_GET_UID)

    def test_set_new_room_nextcloud_mapping_without_group_existence(self):
        self.handlers.nextcloud_room_group_exists = simple_async_mock(
            raises=HTTPError()
        )
        error = self.get_failure(
            self.handlers.update_nextcloud_mapping(
                "room1", "@user1:test", "/directory"
            ),
            SynapseError,
        )

        self.assertEqual(error.value.code, 400)
        self.assertEqual(error.value.errcode, Codes.UNKNOWN)

    def test_set_new_room_nextcloud_mapping_with_group_creation_error(self):
        self.handlers.create_nextcloud_group = simple_async_mock(raises=HTTPError())
        error = self.get_failure(
            self.handlers.update_nextcloud_mapping(
                "room1", "@user1:test", "/directory"
            ),
            SynapseError,
        )

        self.assertEqual(error.value.code, 400)
        self.assertEqual(error.value.errcode, Codes.UNKNOWN)

    def test_set_new_room_nextcloud_mapping_with_share_creation_error(self):
        self.handlers.create_new_nextcloud_share = simple_async_mock(raises=HTTPError())
        error = self.get_failure(
            self.handlers.update_nextcloud_mapping(
                "room1", "@user1:test", "/directory"
            ),
            SynapseError,
        )

        self.assertEqual(error.value.code, 400)
        self.assertEqual(error.value.errcode, Codes.UNKNOWN)

    def test_update_existing_room_nextcloud_mapping_with_delete_share_error(self):
        self.handlers.delete_existing_nextcloud_share = simple_async_mock(
            raises=HTTPError()
        )
        self.get_success(
            self.store.set_room_mapping_with_nextcloud_directory("room1", "/directory")
        )
        error = self.get_failure(
            self.handlers.update_nextcloud_mapping(
                "room1", "@user1:test", "/directory2"
            ),
            SynapseError,
        )

        self.assertEqual(error.value.code, 400)
        self.assertEqual(error.value.errcode, Codes.UNKNOWN)

    def test_remove_user_from_nextcloud_group_with_exception(self):
        user_id = "@user1:test"
        group_name = "room1"
        self.handlers.remove_user_from_nextcloud_group = simple_async_mock(
            raises=HTTPError()
        )

        with self.assertLogs("synapse.handlers.room", level="WARN") as cm:
            self.get_success(
                self.handlers.update_existing_nextcloud_share_for_user(
                    user_id, group_name, "leave"
                )
            )

        self.assertIn(
            "Unable to remove the user {user_id} from the Nextcloud group {group_name} : ".format(
                user_id=user_id, group_name=group_name
            ),
            cm.output[0],
        )

    def test_add_user_to_nextcloud_group_with_exception(self):
        user_id = "@user1:test"
        group_name = "room1"
        self.handlers.add_user_to_nextcloud_group = simple_async_mock(
            raises=HTTPError()
        )

        with self.assertLogs("synapse.handlers.room", level="WARN") as cm:
            self.get_success(
                self.handlers.update_existing_nextcloud_share_for_user(
                    user_id, group_name, "join"
                )
            )

        self.assertIn(
            "Unable to add the user {user_id} to the Nextcloud group {group_name} : ".format(
                user_id=user_id, group_name=group_name
            ),
            cm.output[0],
        )
