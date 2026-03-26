# backend/storage.py - Version unifiée avec un seul fichier users.xml
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from pathlib import Path
import logging
import uuid

logger = logging.getLogger(__name__)

class XMLStorage:
    """Gestionnaire de stockage XML - Un seul fichier users.xml"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.users_file = self.data_dir / "users" / "users.xml"
        self.tables_dir = self.data_dir / "tables"
        self.tournaments_dir = self.data_dir / "tournaments"
        self.history_dir = self.data_dir / "history"
        
        # Créer les répertoires
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        self.tables_dir.mkdir(parents=True, exist_ok=True)
        self.tournaments_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        
        # Nettoyer les anciens fichiers individuels
        self._cleanup_old_files()
        
        # Créer le fichier users.xml s'il n'existe pas
        self._ensure_users_file()
        
        logger.info(f"XMLStorage initialized")
    
    def _cleanup_old_files(self):
        """Supprime les anciens fichiers individuels d'utilisateurs"""
        users_dir = self.data_dir / "users"
        if users_dir.exists():
            for file in users_dir.glob("*.xml"):
                if file.name != "users.xml":
                    file.unlink()
                    logger.info(f"Deleted old file: {file.name}")
    
    def _ensure_users_file(self):
        """Crée le fichier users.xml s'il n'existe pas"""
        if not self.users_file.exists():
            root = ET.Element("users")
            tree = ET.ElementTree(root)
            tree.write(self.users_file, encoding='utf-8', xml_declaration=True)
            logger.info("Created users.xml")
    
    def _serialize_value(self, value: Any) -> str:
        if value is None:
            return ''
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if isinstance(value, (int, float)):
            return str(value)
        return str(value)
    
    def _deserialize_value(self, value: str, value_type: str = 'str') -> Any:
        if not value:
            if value_type == 'int':
                return 0
            if value_type == 'bool':
                return False
            if value_type == 'datetime':
                return datetime.utcnow()
            return ''
        
        try:
            if value_type == 'int':
                return int(value)
            if value_type == 'float':
                return float(value)
            if value_type == 'bool':
                return value.lower() == 'true'
            if value_type == 'datetime':
                try:
                    return datetime.fromisoformat(value)
                except:
                    return datetime.utcnow()
            return value
        except:
            return value
    
    def _write_xml(self, filepath: Path, root: ET.Element):
        rough_string = ET.tostring(root, encoding='utf-8')
        reparsed = minidom.parseString(rough_string)
        pretty_xml = reparsed.toprettyxml(indent="  ", encoding='utf-8')
        with open(filepath, 'wb') as f:
            f.write(pretty_xml)
    
    # ==================== UTILISATEURS ====================
    
    def save_user(self, user_data: Dict[str, Any]) -> str:
        """Sauvegarde un utilisateur dans users.xml"""
        try:
            tree = ET.parse(self.users_file)
            root = tree.getroot()
            
            user_id = user_data.get('id')
            
            # Chercher l'utilisateur existant
            existing_user = None
            for user in root.findall('user'):
                if user.findtext('id') == user_id:
                    existing_user = user
                    break
            
            if existing_user is not None:
                # Mettre à jour
                for key, value in user_data.items():
                    elem = existing_user.find(key)
                    if elem is not None:
                        elem.text = self._serialize_value(value)
                    else:
                        ET.SubElement(existing_user, key).text = self._serialize_value(value)
            else:
                # Créer nouveau
                user_elem = ET.SubElement(root, "user")
                for key, value in user_data.items():
                    ET.SubElement(user_elem, key).text = self._serialize_value(value)
            
            self._write_xml(self.users_file, root)
            logger.info(f"User saved: {user_id}")
            return user_id
            
        except Exception as e:
            logger.error(f"Error saving user: {e}")
            return user_data.get('id', '')
    
    def load_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Charge un utilisateur depuis users.xml"""
        try:
            if not self.users_file.exists():
                return None
            
            tree = ET.parse(self.users_file)
            root = tree.getroot()
            
            for user in root.findall('user'):
                if user.findtext('id') == user_id:
                    return {
                        'id': user.findtext('id'),
                        'username': user.findtext('username'),
                        'email': user.findtext('email'),
                        'avatar': user.findtext('avatar', 'default'),
                        'is_admin': self._deserialize_value(user.findtext('is_admin', 'false'), 'bool'),
                        'status': user.findtext('status', 'active'),
                        'created_at': self._deserialize_value(user.findtext('created_at'), 'datetime'),
                        'last_active': self._deserialize_value(user.findtext('last_active'), 'datetime')
                    }
            return None
        except Exception as e:
            logger.error(f"Error loading user {user_id}: {e}")
            return None
    
    def list_users(self) -> List[str]:
        """Liste tous les IDs utilisateurs"""
        try:
            if not self.users_file.exists():
                return []
            
            tree = ET.parse(self.users_file)
            root = tree.getroot()
            
            user_ids = []
            for user in root.findall('user'):
                user_id = user.findtext('id')
                if user_id:
                    user_ids.append(user_id)
            return user_ids
        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return []
    
    def delete_user(self, user_id: str) -> bool:
        """Supprime un utilisateur"""
        try:
            tree = ET.parse(self.users_file)
            root = tree.getroot()
            
            for user in root.findall('user'):
                if user.findtext('id') == user_id:
                    root.remove(user)
                    self._write_xml(self.users_file, root)
                    return True
            return False
        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            return False
    
    # ==================== TABLES ====================
    
    def save_table(self, table_data: Dict[str, Any]) -> str:
        """Sauvegarde une table"""
        table_id = table_data.get('id', str(uuid.uuid4()))
        filepath = self.tables_dir / f"{table_id}.xml"
        
        root = ET.Element("table")
        for key, value in table_data.items():
            if key != 'players':
                ET.SubElement(root, key).text = self._serialize_value(value)
        
        self._write_xml(filepath, root)
        return table_id
    
    def load_table(self, table_id: str) -> Optional[Dict[str, Any]]:
        filepath = self.tables_dir / f"{table_id}.xml"
        if not filepath.exists():
            return None
        
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            return {key: root.findtext(key, '') for key in ['id', 'name', 'game_type', 'max_players', 'status']}
        except:
            return None
    
    def list_tables(self) -> List[str]:
        return [f.stem for f in self.tables_dir.glob("*.xml")]
    
    def delete_table(self, table_id: str):
        filepath = self.tables_dir / f"{table_id}.xml"
        if filepath.exists():
            filepath.unlink()
