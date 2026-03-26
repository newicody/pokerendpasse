// frontend/js/chat.js
const smileys = ['😀', '😃', '😄', '😁', '😆', '😅', '😂', '🤣', '😊', '😇', '🙂', '🙃', '😉', '😌', '😍', '🥰', '😘', '😗', '😙', '😚', '😋', '😛', '😝', '😜', '🤪', '🤨', '🧐', '🤓', '😎', '🤩', '🥳', '😏', '😒', '😞', '😔', '😟', '😕', '🙁', '☹️', '😣', '😖', '😫', '😩', '🥺', '😢', '😭', '😤', '😠', '😡', '🤬', '🤯', '😳', '🥵', '🥶', '😱', '😨', '😰', '😥', '😓', '🤗', '🤔', '🤭', '🤫', '🤥', '😶', '😐', '😑', '😬', '🙄', '😯', '😦', '😧', '😮', '😲', '🥱', '😴', '🤤', '😪', '😵', '🤐', '🥴', '🤢', '🤮', '🤧', '😷', '🤒', '🤕', '🤑', '🤠', '😈', '👿', '👹', '👺', '💩', '👻', '💀', '👽', '🤖', '🎃', '😺', '😸', '😹', '😻', '😼', '😽', '🙀', '😿', '😾'];

class ChatManager {
    constructor() {
        this.hideJoinMessages = false;
        this.autoConvertSmileys = true;
        this.loadSettings();
        this.initSmileyPicker();
        this.initMediaUpload();
    }
    
    loadSettings() {
        const saved = localStorage.getItem('chat_settings');
        if (saved) {
            const settings = JSON.parse(saved);
            this.hideJoinMessages = settings.hideJoinMessages || false;
            this.autoConvertSmileys = settings.autoConvertSmileys !== false;
        }
    }
    
    saveSettings() {
        localStorage.setItem('chat_settings', JSON.stringify({
            hideJoinMessages: this.hideJoinMessages,
            autoConvertSmileys: this.autoConvertSmileys
        }));
    }
    
    initSmileyPicker() {
        const dropdown = document.getElementById('smileyDropdown');
        if (dropdown) {
            dropdown.innerHTML = smileys.map(s => `<span>${s}</span>`).join('');
            dropdown.querySelectorAll('span').forEach(span => {
                span.onclick = () => {
                    const input = document.getElementById('chatInput');
                    if (input) input.value += span.textContent;
                    dropdown.classList.remove('show');
                };
            });
        }
        
        const smileyBtn = document.getElementById('smileyBtn');
        if (smileyBtn) {
            smileyBtn.onclick = () => {
                const dropdown = document.getElementById('smileyDropdown');
                if (dropdown) dropdown.classList.toggle('show');
            };
        }
        
        document.addEventListener('click', (e) => {
            const dropdown = document.getElementById('smileyDropdown');
            if (dropdown && !dropdown.contains(e.target) && e.target !== smileyBtn) {
                dropdown.classList.remove('show');
            }
        });
    }
    
    initMediaUpload() {
        const mediaBtn = document.getElementById('mediaBtn');
        if (mediaBtn) {
            mediaBtn.onclick = () => {
                const input = document.createElement('input');
                input.type = 'file';
                input.accept = 'image/*,video/*';
                input.onchange = async (e) => {
                    const file = e.target.files[0];
                    if (file) {
                        await this.sendMedia(file);
                    }
                };
                input.click();
            };
        }
    }
    
    async sendMedia(file) {
        if (file.size > 5 * 1024 * 1024) {
            alert('File too large (max 5MB)');
            return;
        }
        
        const reader = new FileReader();
        reader.onload = async (e) => {
            const mediaData = e.target.result;
            const message = {
                type: 'media',
                mediaType: file.type.startsWith('image/') ? 'image' : 'video',
                data: mediaData,
                filename: file.name
            };
            
            if (chatWs && chatWs.readyState === WebSocket.OPEN) {
                chatWs.send(JSON.stringify(message));
            }
        };
        reader.readAsDataURL(file);
    }
    
    formatMessage(message) {
        let text = message.text || '';
        
        // Convertir les URLs en liens
        const urlRegex = /(https?:\/\/[^\s]+)/g;
        text = text.replace(urlRegex, (url) => `<a href="${url}" target="_blank">${url}</a>`);
        
        // Convertir les smileys
        if (this.autoConvertSmileys) {
            const smileyRegex = /(:\)|:\(|:D|:P|;\)|:o|:\|)/g;
            const smileyMap = {
                ':)': '😊',
                ':(': '😞',
                ':D': '😃',
                ':P': '😛',
                ';)': '😉',
                ':o': '😮',
                ':|': '😐'
            };
            text = text.replace(smileyRegex, (match) => smileyMap[match] || match);
        }
        
        return text;
    }
    
    addMediaMessage(username, mediaData, mediaType, filename) {
        const container = document.getElementById('chatMessages');
        const time = new Date().toLocaleTimeString();
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${username === currentUser?.username ? 'self' : 'user'}`;
        
        let mediaHtml = '';
        if (mediaType === 'image') {
            mediaHtml = `<div class="message-media"><img src="${mediaData}" alt="${filename}" onclick="window.open('${mediaData}')"></div>`;
        } else if (mediaType === 'video') {
            mediaHtml = `<div class="message-media"><video controls src="${mediaData}" style="max-width: 100%;"></video></div>`;
        }
        
        messageDiv.innerHTML = `
            <span class="username">${escapeHtml(username)}</span>
            <span class="time">[${time}]</span>
            ${mediaHtml}
            <div class="message-text">${escapeHtml(filename)}</div>
        `;
        
        container.appendChild(messageDiv);
        messageDiv.scrollIntoView({ behavior: 'smooth' });
        
        while (container.children.length > 200) {
            container.removeChild(container.firstChild);
        }
    }
    
    addChatMessage(message) {
        if (message.type === 'system' && this.hideJoinMessages) return;
        
        const container = document.getElementById('chatMessages');
        const time = new Date(message.timestamp).toLocaleTimeString();
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${message.type === 'system' ? 'system' : (message.username === currentUser?.username ? 'self' : 'user')}`;
        
        if (message.type === 'system') {
            messageDiv.innerHTML = `<span class="time">[${time}]</span> ${escapeHtml(message.message)}`;
        } else if (message.mediaType) {
            let mediaHtml = '';
            if (message.mediaType === 'image') {
                mediaHtml = `<div class="message-media"><img src="${message.data}" alt="${message.filename}" onclick="window.open('${message.data}')"></div>`;
            } else if (message.mediaType === 'video') {
                mediaHtml = `<div class="message-media"><video controls src="${message.data}" style="max-width: 100%;"></video></div>`;
            }
            messageDiv.innerHTML = `
                <span class="username">${escapeHtml(message.username)}</span>
                <span class="time">[${time}]</span>
                ${mediaHtml}
                <div class="message-text">${escapeHtml(message.filename || '')}</div>
            `;
        } else {
            const formattedText = this.formatMessage({ text: message.message });
            messageDiv.innerHTML = `
                <span class="username">${escapeHtml(message.username)}</span>
                <span class="time">[${time}]</span>
                <div class="message-text">${formattedText}</div>
            `;
        }
        
        container.appendChild(messageDiv);
        messageDiv.scrollIntoView({ behavior: 'smooth' });
        
        while (container.children.length > 200) {
            container.removeChild(container.firstChild);
        }
    }
    
    showSettingsModal() {
        const modal = document.getElementById('chatSettingsModal');
        if (modal) {
            document.getElementById('hideJoinMessages').checked = this.hideJoinMessages;
            document.getElementById('autoConvertSmileys').checked = this.autoConvertSmileys;
            modal.style.display = 'block';
        }
    }
    
    saveSettingsModal() {
        this.hideJoinMessages = document.getElementById('hideJoinMessages').checked;
        this.autoConvertSmileys = document.getElementById('autoConvertSmileys').checked;
        this.saveSettings();
        closeModal('chatSettingsModal');
        alert('Chat settings saved!');
    }
}

window.chatManager = new ChatManager();

// Ajouter dans initChat()
function initChat() {
    if (!currentUser || isGuest) return;
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;
    
    chatWs = new WebSocket(wsUrl);
    
    chatWs.onopen = () => {
        console.log('Chat connected');
        chatWs.send(JSON.stringify({ type: 'join', user_id: currentUser.id, username: currentUser.username }));
        document.getElementById('chatInput').disabled = false;
        document.getElementById('chatSendBtn').disabled = false;
    };
    
    chatWs.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.mediaType) {
            chatManager.addMediaMessage(message.username, message.data, message.mediaType, message.filename);
        } else {
            chatManager.addChatMessage(message);
        }
        if (message.user_count) {
            document.getElementById('chatUserCount').textContent = `${message.user_count} online`;
        }
    };
    
    chatWs.onclose = () => {
        console.log('Chat disconnected');
        document.getElementById('chatInput').disabled = true;
        document.getElementById('chatSendBtn').disabled = true;
        setTimeout(initChat, 3000);
    };
    
    const chatInput = document.getElementById('chatInput');
    const chatSendBtn = document.getElementById('chatSendBtn');
    
    chatSendBtn.onclick = () => sendChatMessage();
    chatInput.onkeypress = (e) => { if (e.key === 'Enter') sendChatMessage(); };
    
    // Chat settings button
    const chatSettingsBtn = document.getElementById('chatSettingsBtn');
    if (chatSettingsBtn) {
        chatSettingsBtn.onclick = () => chatManager.showSettingsModal();
    }
}

function sendChatMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    if (!message) return;
    
    if (chatWs && chatWs.readyState === WebSocket.OPEN) {
        chatWs.send(JSON.stringify({ type: 'message', username: currentUser.username, message: message }));
        input.value = '';
    }
}
