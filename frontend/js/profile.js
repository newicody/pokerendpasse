/**
 * profile.js — Page profil utilisateur
 * Version corrigée — pas de dépendance chatManager
 */

'use strict';

let currentUser = null;

async function init() {
    console.log('Initializing profile...');
    await checkAuth();
    if (!currentUser) return; // redirigé vers login
    loadProfile();
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
        if (!currentUser || !currentUser.id) {
            window.location.href = '/login';
            return;
        }
        console.log('User loaded:', currentUser.username);
    } catch (error) {
        console.error('Auth check failed:', error);
        window.location.href = '/login';
    }
}

function loadProfile() {
    document.getElementById('username').textContent = currentUser.username;
    document.getElementById('email').value = currentUser.email || '';
    updateAvatar(currentUser.avatar || 'default');
}

function updateAvatar(avatarName) {
    const avatarImg = document.getElementById('avatarImg');
    const predefined = ['default', 'panda', 'tiger', 'dragon', 'phoenix'];

    let avatarUrl;
    if (avatarName && avatarName.startsWith('/uploads/')) {
        avatarUrl = avatarName;
    } else if (avatarName && predefined.includes(avatarName)) {
        avatarUrl = `/assets/images/avatars/${avatarName}.svg`;
    } else {
        avatarUrl = '/assets/images/avatars/default.svg';
    }

    if (avatarImg) avatarImg.src = avatarUrl;

    // Highlight selected avatar option
    document.querySelectorAll('.avatar-option').forEach(opt => {
        opt.classList.toggle('selected', predefined.includes(avatarName) && opt.dataset.avatar === avatarName);
    });

    // Update hidden input
    const hidden = document.getElementById('selectedAvatar');
    if (hidden) hidden.value = avatarName;
}

async function saveProfile() {
    const email = document.getElementById('email')?.value || '';
    const avatar = document.getElementById('selectedAvatar')?.value || 'default';

    try {
        const response = await fetch('/api/auth/me', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, avatar })
        });

        if (response.ok) {
            const updatedUser = await response.json();
            currentUser = updatedUser;
            updateAvatar(currentUser.avatar || 'default');
            alert('Profile updated successfully!');
        } else {
            const error = await response.json().catch(() => ({}));
            alert('Error: ' + (error.detail || 'Update failed'));
        }
    } catch (error) {
        console.error('Error saving profile:', error);
        alert('Failed to save profile');
    }
}

async function changePassword() {
    const currentPassword = document.getElementById('currentPassword')?.value;
    const newPassword = document.getElementById('newPassword')?.value;
    const confirmPassword = document.getElementById('confirmPassword')?.value;

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
            const error = await response.json().catch(() => ({}));
            alert('Error: ' + (error.detail || 'Password change failed'));
        }
    } catch (error) {
        console.error('Error changing password:', error);
        alert('Failed to change password');
    }
}

function showChangePasswordModal() {
    const modal = document.getElementById('changePasswordModal');
    if (modal) {
        modal.style.display = 'flex';
        document.getElementById('currentPassword').value = '';
        document.getElementById('newPassword').value = '';
        document.getElementById('confirmPassword').value = '';
    }
}

function closeModal() {
    const modal = document.getElementById('changePasswordModal');
    if (modal) modal.style.display = 'none';
}

async function logout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
    } catch (_) { }
    window.location.href = '/';
}

function setupEventListeners() {
    document.getElementById('saveProfile')?.addEventListener('click', saveProfile);
    document.getElementById('changePasswordBtn')?.addEventListener('click', showChangePasswordModal);
    document.getElementById('logoutBtn')?.addEventListener('click', logout);
    document.getElementById('closePasswordModal')?.addEventListener('click', closeModal);

    // Close modal on close button or outside click
    document.querySelectorAll('.modal .close').forEach(btn => {
        btn.onclick = closeModal;
    });
    window.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) closeModal();
    });

    // Upload custom avatar
    document.getElementById('uploadAvatarBtn')?.addEventListener('click', () => {
        document.getElementById('avatarUpload')?.click();
    });

    document.getElementById('avatarUpload')?.addEventListener('change', async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;

        if (file.size > 2 * 1024 * 1024) {
            alert('File too large. Max 2MB.');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/auth/avatar', {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                const data = await response.json();
                updateAvatar(data.avatar_url);
                document.getElementById('selectedAvatar').value = data.avatar_url;
                alert('Avatar uploaded successfully!');
            } else {
                const error = await response.json().catch(() => ({}));
                alert('Error: ' + (error.detail || 'Upload failed'));
            }
        } catch (error) {
            console.error('Error uploading avatar:', error);
            alert('Failed to upload avatar');
        }
    });

    // Predefined avatar selection
    document.querySelectorAll('.avatar-option').forEach(avatar => {
        avatar.addEventListener('click', () => {
            const name = avatar.dataset.avatar;
            document.getElementById('selectedAvatar').value = name;
            updateAvatar(name);
        });
    });

    document.getElementById('submitPasswordChange')?.addEventListener('click', changePassword);
}

// Start
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
