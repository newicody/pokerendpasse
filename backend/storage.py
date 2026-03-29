# backend/storage.py
import xml.etree.ElementTree as ET
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class XMLStorage:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.users_file = self.data_dir / "users" / "users.xml"
        self.tables_dir = self.data_dir / "tables"
        self.tournaments_dir = self.data_dir / "tournaments"
        self.history_dir = self.data_dir / "history"

        for d in (self.users_file.parent, self.tables_dir, self.tournaments_dir, self.history_dir):
            d.mkdir(parents=True, exist_ok=True)

        self._ensure_users_file()
        logger.info("XMLStorage initialized")

    def _ensure_users_file(self):
        if not self.users_file.exists():
            root = ET.Element("users")
            ET.ElementTree(root).write(self.users_file, encoding='utf-8', xml_declaration=True)

    def _serialize_value(self, value: Any) -> str:
        if value is None:
            return ''
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    # ── Users ─────────────────────────────────────────────────────────────────

    def save_user(self, user_id: str, data: dict):
        try:
            tree = ET.parse(self.users_file)
            root = tree.getroot()
            # Chercher si l'utilisateur existe
            existing = None
            for ue in root.findall('user'):
                if ue.findtext('id') == user_id:
                    existing = ue
                    break

            if existing is None:
                existing = ET.SubElement(root, 'user')

            # Clear and repopulate
            for child in list(existing):
                existing.remove(child)

            for k, v in data.items():
                if k.startswith('_'):
                    continue
                el = ET.SubElement(existing, k)
                el.text = self._serialize_value(v)

            tree.write(self.users_file, encoding='utf-8', xml_declaration=True)
        except Exception as e:
            logger.error(f"Save user {user_id}: {e}")

    def load_user(self, user_id: str) -> Optional[dict]:
        try:
            tree = ET.parse(self.users_file)
            for ue in tree.getroot().findall('user'):
                if ue.findtext('id') == user_id:
                    return {child.tag: (child.text or '') for child in ue}
            return None
        except Exception:
            return None

    def list_users(self) -> List[str]:
        try:
            tree = ET.parse(self.users_file)
            return [ue.findtext('id') for ue in tree.getroot().findall('user') if ue.findtext('id')]
        except Exception:
            return []

    def delete_user(self, user_id: str):
        try:
            tree = ET.parse(self.users_file)
            root = tree.getroot()
            for ue in root.findall('user'):
                if ue.findtext('id') == user_id:
                    root.remove(ue)
                    tree.write(self.users_file, encoding='utf-8', xml_declaration=True)
                    return
        except Exception as e:
            logger.error(f"Delete user {user_id}: {e}")
