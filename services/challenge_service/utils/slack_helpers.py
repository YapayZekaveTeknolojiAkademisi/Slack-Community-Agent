import time
from typing import Callable, List, Optional, TypeVar

from slack_sdk.errors import SlackApiError

from packages.slack.client import slack_client
from packages.settings import get_settings
from ..logger import get_logger

logger = get_logger("challenge_service.utils.slack")

_T = TypeVar("_T")
_MAX_RETRIES = 3


def _call(fn: Callable[..., _T], *args, **kwargs) -> _T:
    """Slack API çağrısını rate limit hatasında backoff ile yeniden dener."""
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except SlackApiError as exc:
            if exc.response.get("error") == "ratelimited" and attempt < _MAX_RETRIES - 1:
                wait = int(exc.response.headers.get("Retry-After", 1))
                logger.warning("Slack rate limited — %ds bekleniliyor (deneme %d/%d)", wait, attempt + 1, _MAX_RETRIES)
                time.sleep(wait)
                continue
            raise


class SlackHelper:
    _bot_user_id: str | None = None
    _user_client_user_id: str | None = None

    @property
    def _workspace_owner_id(self) -> Optional[str]:
        return get_settings().slack_workspace_owner_id

    @property
    def _admin_slack_id(self) -> str:
        return get_settings().slack_admin_slack_id or ""

    @property
    def bot_client(self):
        return slack_client.bot_client

    @property
    def user_client(self):
        return slack_client.user_client

    def get_bot_user_id(self) -> str | None:
        if not self._bot_user_id:
            try:
                self._bot_user_id = _call(slack_client.bot_client.auth_test).get("user_id")
            except Exception as e:
                logger.error(f"Failed to get bot user_id: {e}")
        return self._bot_user_id

    def get_user_client_user_id(self) -> str | None:
        if not self._user_client_user_id:
            try:
                self._user_client_user_id = _call(slack_client.user_client.auth_test).get("user_id")
            except Exception as e:
                logger.error(f"Failed to get user_client user_id: {e}")
        return self._user_client_user_id

    def _find_channel_by_name(self, name: str) -> Optional[str]:
        """Find an existing private channel by name (recovery for name_taken).
        If the channel is archived, unarchives it so it can be reused."""
        try:
            cursor = None
            while True:
                kwargs = {"types": "private_channel", "limit": 200, "exclude_archived": False}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = slack_client.user_client.conversations_list(**kwargs)
                for ch in resp.get("channels", []):
                    if ch.get("name") == name:
                        channel_id = ch["id"]
                        if ch.get("is_archived"):
                            try:
                                slack_client.user_client.conversations_unarchive(channel=channel_id)
                                logger.info(f"Unarchived recovered channel {channel_id} ('{name}')")
                            except Exception as e:
                                logger.warning(f"Could not unarchive channel {channel_id}: {e}")
                        return channel_id
                cursor = resp.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        except Exception as e:
            logger.error(f"Error finding channel by name '{name}': {e}")
        return None

    def create_private_channel(self, name: str) -> Optional[str]:
        """Create a private channel, invite the bot, and return the channel ID."""
        try:
            response = _call(slack_client.user_client.conversations_create, name=name, is_private=True)
            if not response["ok"]:
                if response.get("error") == "name_taken":
                    logger.warning(f"Channel '{name}' already exists, recovering existing ID.")
                    return self._find_channel_by_name(name)
                return None
            channel_id = response["channel"]["id"]
            user_client_id = self.get_user_client_user_id()
            to_bootstrap = []
            bot_id = self.get_bot_user_id()
            if bot_id:
                to_bootstrap.append(bot_id)
            owner_id = self._workspace_owner_id
            if owner_id and owner_id != user_client_id:
                to_bootstrap.append(owner_id)
            admin_id = self._admin_slack_id
            if admin_id and admin_id != user_client_id and admin_id not in to_bootstrap:
                to_bootstrap.append(admin_id)
            if to_bootstrap:
                try:
                    _call(slack_client.user_client.conversations_invite, channel=channel_id, users=to_bootstrap)
                except Exception as e:
                    logger.warning(f"Could not bootstrap channel {channel_id}: {e}")
            return channel_id
        except Exception as e:
            logger.error(f"Error creating channel {name}: {str(e)}")
        return None

    def invite_users_to_channel(self, channel_id: str, user_ids: List[str]):
        """Invite users to a channel, skipping the user_client owner (already in channel)."""
        owner_id = self.get_user_client_user_id()
        to_invite = [uid for uid in user_ids if uid != owner_id]
        if not to_invite:
            return
        try:
            _call(slack_client.user_client.conversations_invite, channel=channel_id, users=to_invite)
        except Exception as e:
            logger.error(f"Error inviting users to {channel_id}: {str(e)}")

    @staticmethod
    def archive_channel(channel_id: str):
        """Archive a channel using User Token."""
        try:
            _call(slack_client.user_client.conversations_archive, channel=channel_id)
        except Exception as e:
            logger.error(f"Error archiving channel {channel_id}: {str(e)}")

    def send_announcement(self, channel_id: str, text: str, blocks: Optional[List[dict]] = None):
        """Send a message to a channel using User Token (always a member of private channels)."""
        try:
            _call(slack_client.user_client.chat_postMessage, channel=channel_id, text=text, blocks=blocks)
        except Exception as e:
            logger.error(f"Error sending announcement to {channel_id}: {str(e)}")

    def post_message(self, channel_id: str, text: str, blocks: Optional[List[dict]] = None) -> Optional[str]:
        """Send a message to a private channel using User Token and return its ts."""
        try:
            resp = _call(slack_client.user_client.chat_postMessage, channel=channel_id, text=text, blocks=blocks)
            return resp.get("ts")
        except Exception as e:
            logger.error(f"Error posting message to {channel_id}: {str(e)}")
            return None

    def post_public_message(self, channel_id: str, text: str, blocks: Optional[List[dict]] = None) -> Optional[str]:
        """Send a message to a public channel using Bot Token and return its ts."""
        try:
            resp = _call(slack_client.bot_client.chat_postMessage, channel=channel_id, text=text, blocks=blocks)
            return resp.get("ts")
        except Exception as e:
            logger.error(f"Error posting public message to {channel_id}: {str(e)}")
            return None

    def update_message(self, channel_id: str, ts: str, text: str, blocks: Optional[List[dict]] = None):
        """Update an existing message."""
        try:
            _call(slack_client.user_client.chat_update, channel=channel_id, ts=ts, text=text, blocks=blocks)
        except Exception as e:
            logger.error(f"Error updating message {ts} in {channel_id}: {str(e)}")

slack_helper = SlackHelper()
