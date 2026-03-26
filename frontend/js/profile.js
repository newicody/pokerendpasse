// frontend/js/profile.js
let currentUser = null;

async function init() {
    console.log('Initializing profile...');
    await checkAuth();
    await loadProfile();
    setupEventListeners();
}

async function checkAuth() {
    try {
        const response = await fetch('/api/auth/me');
        if (!response.ok) {
            window.location.href = '/login';
            return;
        }
        currentUser = await response.json();
        if (!currentUser) {
            window.location.href = '/login';
            return;
        }
        console.log('User loaded:', currentUser);
    } catch (error) {
        console.error('Auth check failed:', error);
        window.location.href = '/login';
    }
}

async function loadProfile() {
    try {
        const response = await fetch('/api/auth/me');
        if (response.ok) {
            currentUser = await response.json();
        }
        
        document.getElementById('username').textContent = currentUser.username;
        document.getElementById('email').value = currentUser.email || '';
        
        updateAvatar(currentUser.avatar || 'default');
    } catch (error) {
        console.error('Error loading profile:', error);
    }
}

function updateAvatar(avatarName) {
    const avatarImg = document.getElementById('avatarImg');
    const predefinedAvatars = ['default', 'panda', 'tiger', 'dragon', 'phoenix'];
    
    let avatarUrl;
    if (avatarName && predefinedAvatars.includes(avatarName)) {
        avatarUrl = `/assets/images/avatars/${avatarName}.svg`;
    } else if (avatarName && avatarName.startsWith('/uploads/')) {
        avatarUrl = avatarName;
    } else {
        avatarUrl = '/assets/images/avatars/default.svg';
    }
    
    if (avatarImg) avatarImg.src = avatarUrl;
    
    const avatarOptions = document.querySelectorAll('.avatar-option');
    avatarOptions.forEach(opt => {
        if (opt.dataset.avatar === avatarName && predefinedAvatars.includes(avatarName)) {
            opt.classList.add('selected');
        } else {
            opt.classList.remove('selected');
        }
    });
}

async function saveProfile() {
    const email = document.getElementById('email').value;
    const avatar = document.getElementById('selectedAvatar').value;
    
    try {
        const response = await fetch('/api/auth/me', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, avatar })
        });
        
        if (response.ok) {
            const updatedUser = await response.json();
            currentUser = updatedUser;
            localStorage.setItem('poker_user', JSON.stringify({ id: currentUser.id }));
            alert('Profile updated successfully!');
            updateAvatar(currentUser.avatar || 'default');
        } else {
            const error = await response.json();
            alert('Error: ' + (error.detail || 'Update failed'));
        }
    } catch (error) {
        console.error('Error saving profile:', error);
        alert('Failed to save profile');
    }
}

function setupEventListeners() {
    document.getElementById('saveProfile')?.addEventListener('click', saveProfile);
    document.getElementById('changePasswordBtn')?.addEventListener('click', showChangePasswordModal);
    document.getElementById('logoutBtn')?.addEventListener('click', logout);
    document.getElementById('closeModal')?.addEventListener('click', closeModal);
    document.querySelector('#changePasswordModal .close')?.addEventListener('click', closeModal);
    
    document.getElementById('uploadAvatarBtn')?.addEventListener('click', () => {
        document.getElementById('avatarUpload').click();
    });
    
    document.getElementById('avatarUpload')?.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch('/api/auth/avatar', {
                method: 'POST',
                body: formData
            });
            
            if (response.ok) {
                const data = await response.json();
                document.getElementById('avatarImg').src = data.avatar_url;
                document.getElementById('selectedAvatar').value = data.avatar_url;
                alert('Avatar uploaded successfully!');
            } else {
                const error = await response.json();
                alert('Error: ' + (error.detail || 'Upload failed'));
            }
        } catch (error) {
            console.error('Error uploading avatar:', error);
            alert('Failed to upload avatar');
        }
    });
    
    const avatars = document.querySelectorAll('.avatar-option');
    avatars.forEach(avatar => {
        avatar.addEventListener('click', () => {
            const avatarName = avatar.dataset.avatar;
            document.getElementById('selectedAvatar').value = avatarName;
            updateAvatar(avatarName);
            avatars.forEach(a => a.classList.remove('selected'));
            avatar.classList.add('selected');
        });
    });
    
    document.getElementById('submitPasswordChange')?.addEventListener('click', changePassword);
}

function showChangePasswordModal() {
    const modal = document.getElementById('changePasswordModal');
    if (modal) {
        modal.style.display = 'block';
        document.getElementById('currentPassword').value = '';
        document.getElementById('newPassword').value = '';
        document.getElementById('confirmPassword').value = '';
    }
}

async function changePassword() {
    const currentPassword = document.getElementById('currentPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    
    if (!currentPassword || !newPassword) {
        alert('Please fill in all fields');
        return;
    }
    
    if (newPassword !== confirmPassword) {
        alert('New passwords do not match');
        return;
    }
    
    if (newPassword.length < 6) {
        alert('Password must be at least 6 characters');
        return;
    }
    
    try {
        const response = await fetch('/api/auth/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
        });
        
        if (response.ok) {
            alert('Password changed successfully!');
            closeModal();
        } else {
            const error = await response.json();
            alert('Error: ' + (error.detail || 'Password change failed'));
        }
    } catch (error) {
        console.error('Error changing password:', error);
        alert('Failed to change password');
    }
}

async function logout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
        window.location.href = '/';
    } catch (error) {
        console.error('Logout error:', error);
        window.location.href = '/';
    }
}

function closeModal() {
    const modal = document.getElementById('changePasswordModal');
    if (modal) modal.style.display = 'none';
}

init();
