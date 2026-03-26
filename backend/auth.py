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
    """Gestionnaire d'authentification avec stockage XML et cryptage bcrypt"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.users_file = self.data_dir / "users" / "users.xml"
        self.sessions_dir = self.data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_users_file()

    def _ensure_users_file(self):
        """Crée le fichier users.xml s'il n'existe pas"""
        if not self.users_file.exists():
            root = ET.Element("users")
            tree = ET.ElementTree(root)
            tree.write(self.users_file, encoding='utf-8', xml_declaration=True)
            logger.info("Created new users.xml file")
        else:
            # Vérifier que le fichier est valide
            try:
                tree = ET.parse(self.users_file)
                root = tree.getroot()
                # Si la racine n'est pas "users", corriger
                if root.tag != 'users':
                    logger.warning(f"Invalid users.xml structure, recreating...")
                    # Sauvegarder l'ancien
                    import shutil
                    shutil.copy(self.users_file, self.users_file.with_suffix('.xml.bak'))
                    # Créer un nouveau
                    new_root = ET.Element("users")
                    # Essayer de récupérer les utilisateurs existants
                    for user in root.findall('user'):
                        new_root.append(user)
                    tree = ET.ElementTree(new_root)
                    tree.write(self.users_file, encoding='utf-8', xml_declaration=True)
            except Exception as e:
                logger.error(f"Error reading users.xml: {e}")
                # Créer une sauvegarde
                import shutil
                if self.users_file.exists():
                    shutil.copy(self.users_file, self.users_file.with_suffix('.xml.bak'))
            
                root = ET.Element("users")
                tree = ET.ElementTree(root)
                tree.write(self.users_file, encoding='utf-8', xml_declaration=True)

    def _hash_password(self, password: str) -> str:
        """Hash un mot de passe avec bcrypt"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def _verify_password(self, password: str, hashed: str) -> bool:
        """Vérifie un mot de passe"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception:
            return False
    
    def create_user(self, username: str, password: str, email: str = None) -> bool:
        """Crée un nouvel utilisateur"""
        try:
            tree = ET.parse(self.users_file)
            root = tree.getroot()
            
            # Vérifier si l'utilisateur existe déjà
            for user in root.findall('user'):
                if user.findtext('username') == username:
                    logger.warning(f"User {username} already exists")
                    return False
            
            # Créer le nouvel utilisateur
            user_elem = ET.SubElement(root, 'user')
            user_id = str(uuid.uuid4())
            ET.SubElement(user_elem, 'id').text = user_id
            ET.SubElement(user_elem, 'username').text = username
            ET.SubElement(user_elem, 'email').text = email or ''
            
            # Hash du mot de passe
            password_hash = self._hash_password(password)
            ET.SubElement(user_elem, 'password_hash').text = password_hash
            
            ET.SubElement(user_elem, 'avatar').text = 'default'
            ET.SubElement(user_elem, 'created_at').text = datetime.utcnow().isoformat()
            ET.SubElement(user_elem, 'last_login').text = ''
            ET.SubElement(user_elem, 'is_admin').text = 'false'
            ET.SubElement(user_elem, 'status').text = 'active'
            
            tree.write(self.users_file, encoding='utf-8', xml_declaration=True)
            logger.info(f"User created: {username} ({user_id})")
            return True
            
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return False
    
    def authenticate(self, username: str, password: str) -> Optional[Dict]:
        """Authentifie un utilisateur"""
        try:
            tree = ET.parse(self.users_file)
            root = tree.getroot()
            
            for user in root.findall('user'):
                if user.findtext('username') == username:
                    stored_hash = user.findtext('password_hash')
                    if not stored_hash:
                        continue
                    
                    if self._verify_password(password, stored_hash):
                        return {
                            'id': user.findtext('id'),
                            'username': username,
                            'email': user.findtext('email'),
                            'avatar': user.findtext('avatar', 'default'),
                            'is_admin': user.findtext('is_admin', 'false') == 'true',
                            'status': user.findtext('status', 'active')
                        }
            return None
            
        except Exception as e:
            logger.error(f"Error authenticating: {e}")
            return None
    
    def create_session(self, user_id: str) -> str:
        """Crée une session pour un utilisateur"""
        session_id = secrets.token_urlsafe(32)
        session_file = self.sessions_dir / f"{session_id}.xml"
        
        root = ET.Element("session")
        ET.SubElement(root, 'user_id').text = user_id
        ET.SubElement(root, 'created_at').text = datetime.utcnow().isoformat()
        ET.SubElement(root, 'expires_at').text = (datetime.utcnow() + timedelta(days=7)).isoformat()
        ET.SubElement(root, 'last_activity').text = datetime.utcnow().isoformat()
        
        tree = ET.ElementTree(root)
        tree.write(session_file, encoding='utf-8', xml_declaration=True)
        
        return session_id
    
    def validate_session(self, session_id: str) -> Optional[str]:
        """Valide une session et retourne l'user_id"""
        session_file = self.sessions_dir / f"{session_id}.xml"
        if not session_file.exists():
            return None
        
        try:
            tree = ET.parse(session_file)
            root = tree.getroot()
            
            expires_at = datetime.fromisoformat(root.findtext('expires_at'))
            if expires_at < datetime.utcnow():
                session_file.unlink()
                return None
            
            # Mettre à jour la dernière activité
            root.find('last_activity').text = datetime.utcnow().isoformat()
            tree.write(session_file, encoding='utf-8', xml_declaration=True)
            
            return root.findtext('user_id')
            
        except Exception as e:
            logger.error(f"Error validating session: {e}")
            return None
    
    def delete_session(self, session_id: str):
        """Supprime une session"""
        session_file = self.sessions_dir / f"{session_id}.xml"
        if session_file.exists():
            session_file.unlink()
    # backend/auth.py - Modifier get_user_by_id
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Récupère un utilisateur par son ID"""
        try:
            tree = ET.parse(self.users_file)
            root = tree.getroot()
        
            for user in root.findall('user'):
                if user.findtext('id') == user_id:
                    return {
                        'id': user_id,
                        'username': user.findtext('username'),
                        'email': user.findtext('email'),
                        'avatar': user.findtext('avatar', 'default'),
                        'is_admin': user.findtext('is_admin', 'false') == 'true',
                        'status': user.findtext('status', 'active')
                    }
            return None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
# backend/auth.py - Vérifier que l'avatar est bien sauvegardé
    def update_user(self, user_id: str, data: Dict) -> bool:
        """Met à jour un utilisateur"""
        try:
            tree = ET.parse(self.users_file)
            root = tree.getroot()
        
            for user in root.findall('user'):
                if user.findtext('id') == user_id:
                    for key, value in data.items():
                        elem = user.find(key)
                        if elem is not None:
                            elem.text = str(value)
                        else:
                            ET.SubElement(user, key).text = str(value)
                
                    tree.write(self.users_file, encoding='utf-8', xml_declaration=True)
                    logger.info(f"User {user_id} updated: {data}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error updating user: {e}")
            return False
    
    def update_password(self, user_id: str, new_password: str) -> bool:
        """Met à jour le mot de passe d'un utilisateur"""
        try:
            password_hash = self._hash_password(new_password)
            return self.update_user(user_id, {'password_hash': password_hash})
        except Exception as e:
            logger.error(f"Error updating password: {e}")
            return False

# Instance globale
auth_manager = AuthManager()
