# backend/auth.py
import bcrypt
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict
import logging
import uuid

logger = logging.getLogger(__name__)


class AuthManager:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.users_file = self.data_dir / "users" / "users.xml"
        self.sessions_dir = self.data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_users_file()

    def _ensure_users_file(self):
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.users_file.exists():
            root = ET.Element("users")
            ET.ElementTree(root).write(self.users_file, encoding='utf-8', xml_declaration=True)
            logger.info("Created users.xml")
        else:
            try:
                tree = ET.parse(self.users_file)
                if tree.getroot().tag != 'users':
                    import shutil
                    shutil.copy(self.users_file, self.users_file.with_suffix('.xml.bak'))
                    new_root = ET.Element("users")
                    for u in tree.getroot().findall('user'):
                        new_root.append(u)
                    ET.ElementTree(new_root).write(self.users_file, encoding='utf-8', xml_declaration=True)
            except Exception as e:
                logger.error(f"Error validating users.xml: {e}")
                root = ET.Element("users")
                ET.ElementTree(root).write(self.users_file, encoding='utf-8', xml_declaration=True)

    def _hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def _verify_password(self, password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception:
            return False

    def create_user(self, username: str, password: str, email: str = None,
                    is_admin: bool = False) -> bool:
        try:
            tree = ET.parse(self.users_file)
            root = tree.getroot()
            for u in root.findall('user'):
                if u.findtext('username') == username:
                    return False  # already exists

            user_id = str(uuid.uuid4())
            ue = ET.SubElement(root, 'user')
            ET.SubElement(ue, 'id').text = user_id
            ET.SubElement(ue, 'username').text = username
            ET.SubElement(ue, 'password_hash').text = self._hash_password(password)
            ET.SubElement(ue, 'email').text = email or ''
            ET.SubElement(ue, 'avatar').text = 'default'
            ET.SubElement(ue, 'created_at').text = datetime.utcnow().isoformat()
            ET.SubElement(ue, 'last_login').text = ''
            ET.SubElement(ue, 'is_admin').text = str(is_admin).lower()
            ET.SubElement(ue, 'status').text = 'active'
            tree.write(self.users_file, encoding='utf-8', xml_declaration=True)
            logger.info(f"User created: {username} ({user_id})")
            return True
        except Exception as e:
            logger.error(f"Create user: {e}")
            return False

    def authenticate(self, username: str, password: str) -> Optional[Dict]:
        try:
            tree = ET.parse(self.users_file)
            for u in tree.getroot().findall('user'):
                if u.findtext('username') == username:
                    pw_hash = u.findtext('password_hash')
                    if pw_hash and self._verify_password(password, pw_hash):
                        return {
                            'id': u.findtext('id'),
                            'username': username,
                            'email': u.findtext('email'),
                            'avatar': u.findtext('avatar', 'default'),
                            'is_admin': u.findtext('is_admin', 'false') == 'true',
                            'status': u.findtext('status', 'active'),
                        }
            return None
        except Exception as e:
            logger.error(f"Authenticate: {e}")
            return None

    def create_session(self, user_id: str) -> str:
        session_id = secrets.token_urlsafe(32)
        sf = self.sessions_dir / f"{session_id}.xml"
        root = ET.Element("session")
        ET.SubElement(root, 'user_id').text = user_id
        ET.SubElement(root, 'created_at').text = datetime.utcnow().isoformat()
        ET.SubElement(root, 'expires_at').text = (datetime.utcnow() + timedelta(days=7)).isoformat()
        ET.ElementTree(root).write(sf, encoding='utf-8', xml_declaration=True)
        return session_id

    def validate_session(self, session_id: str) -> Optional[str]:
        sf = self.sessions_dir / f"{session_id}.xml"
        if not sf.exists():
            return None
        try:
            tree = ET.parse(sf)
            root = tree.getroot()
            expires = root.findtext('expires_at')
            if expires and datetime.fromisoformat(expires) < datetime.utcnow():
                sf.unlink(missing_ok=True)
                return None
            return root.findtext('user_id')
        except Exception:
            return None

    def invalidate_session(self, session_id: str):
        try:
            (self.sessions_dir / f"{session_id}.xml").unlink(missing_ok=True)
        except Exception:
            pass

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        try:
            tree = ET.parse(self.users_file)
            for u in tree.getroot().findall('user'):
                if u.findtext('id') == user_id:
                    return {
                        'id': user_id,
                        'username': u.findtext('username'),
                        'email': u.findtext('email'),
                        'avatar': u.findtext('avatar', 'default'),
                        'is_admin': u.findtext('is_admin', 'false') == 'true',
                        'status': u.findtext('status', 'active'),
                    }
            return None
        except Exception:
            return None

    def list_users(self) -> list:
        try:
            tree = ET.parse(self.users_file)
            return [
                {
                    'id': u.findtext('id'),
                    'username': u.findtext('username'),
                    'email': u.findtext('email'),
                    'avatar': u.findtext('avatar', 'default'),
                    'is_admin': u.findtext('is_admin', 'false') == 'true',
                    'status': u.findtext('status', 'active'),
                    'created_at': u.findtext('created_at', ''),
                }
                for u in tree.getroot().findall('user')
            ]
        except Exception:
            return []

    def update_user(self, user_id: str, **kwargs) -> bool:
        try:
            tree = ET.parse(self.users_file)
            for u in tree.getroot().findall('user'):
                if u.findtext('id') == user_id:
                    for key, val in kwargs.items():
                        el = u.find(key)
                        if el is None:
                            el = ET.SubElement(u, key)
                        el.text = str(val) if val is not None else ''
                    tree.write(self.users_file, encoding='utf-8', xml_declaration=True)
                    return True
            return False
        except Exception as e:
            logger.error(f"Update user: {e}")
            return False


auth_manager = AuthManager()
