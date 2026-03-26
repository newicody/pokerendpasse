// frontend/js/websocket.js
class PokerWebSocket {
    constructor(tableId, userId, onMessage, onConnect, onDisconnect) {
        this.tableId = tableId;
        this.userId = userId;
        this.onMessage = onMessage;
        this.onConnect = onConnect;
        this.onDisconnect = onDisconnect;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 3000;
    }
    
    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/ws/chat`;
        
        console.log('Connecting to chat WebSocket:', url);
        
        try {
            this.ws = new WebSocket(url);
            
            this.ws.onopen = () => {
                console.log('Chat WebSocket connected');
                this.reconnectAttempts = 0;
                
                // Envoyer les informations d'identification
                const userData = {
                    type: 'join',
                    user_id: this.userId,
                    username: window.currentUser?.username || 'Guest'
                };
                this.send(userData);
                
                if (this.onConnect) this.onConnect();
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    if (this.onMessage) this.onMessage(message);
                } catch (e) {
                    console.error('Error parsing message:', e);
                }
            };
            
            this.ws.onclose = () => {
                console.log('Chat WebSocket closed');
                if (this.onDisconnect) this.onDisconnect();
                this.reconnect();
            };
            
            this.ws.onerror = (error) => {
                console.error('Chat WebSocket error:', error);
            };
            
        } catch (error) {
            console.error('Failed to create WebSocket:', error);
            this.reconnect();
        }
    }
    
    reconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('Max reconnect attempts reached');
            return;
        }
        
        this.reconnectAttempts++;
        console.log(`Reconnecting attempt ${this.reconnectAttempts}...`);
        
        setTimeout(() => {
            this.connect();
        }, this.reconnectDelay);
    }
    
    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else {
            console.warn('WebSocket not open, cannot send:', data);
        }
    }
    
    sendMessage(message) {
        this.send({
            type: 'message',
            message: message
        });
    }
    
    disconnect() {
        if (this.ws) {
            this.send({ type: 'leave' });
            this.ws.close();
        }
    }
}
