const express = require('express');
const http = require('http');
const mqtt = require('mqtt');
const { WebSocketServer } = require('ws');

// --- 設定 ---
const MQTT_BROKER = 'mqtt://150.65.179.132:7883';
const CID = '53965d6805152d95';
const HTTP_PORT = 3001;
const WS_PORT = 8080;

// ★ 監視対象デバイス (PIRのみ)
const DEVICES = [
    // 1F Living (9分割用)
    'PIR1', 'PIR2', 'PIR3', 'PIR4',
    // 1F Others
    'PIR18', 'PIR13', 'PIR11', 'PIR5', 'PIR21', 'PIR17',
    // 2F
    'PIR6', 'PIR9', 'PIR20', 'PIR19', 'PIR24', 'PIR22', 'PIR8', 'PIR10', 'PIR15'
];

// --- サーバーセットアップ ---
const app = express();
app.use(express.static(__dirname));
const server = http.createServer(app);
server.listen(HTTP_PORT, () => {
    console.log(`[HTTP] サーバー起動: http://localhost:${HTTP_PORT}`);
});

const wss = new WebSocketServer({ port: WS_PORT });
console.log(`[WS] WebSocketサーバー起動: ws://localhost:${WS_PORT}`);

function broadcast(data) {
    const jsonData = JSON.stringify(data);
    wss.clients.forEach(client => {
        if (client.readyState === 1) client.send(jsonData);
    });
}

// --- MQTTクライアント ---
const mqttClient = mqtt.connect(MQTT_BROKER);

mqttClient.on('connect', () => {
    console.log(`[MQTT] ブローカーに接続しました: ${MQTT_BROKER}`);
    DEVICES.forEach(deviceId => {
        const topic = `/server/${CID}/${deviceId}/properties/+`;
        mqttClient.subscribe(topic);
    });
});

mqttClient.on('message', (topic, payload) => {
    try {
        const parts = topic.split('/');
        const deviceId = parts[3];
        const propertyName = parts[5];

        if (!DEVICES.includes(deviceId)) return;

        const data = JSON.parse(payload.toString());

        // PIRセンサーの処理のみ
        if (deviceId.startsWith('PIR')) {
            if (propertyName === 'motion' || propertyName === 'motion_raw') {
                // motion_raw または motion のどちらかを受信したら送る
                const state = (propertyName === 'motion_raw' ? data.motion_raw : data.motion);

                broadcast({
                    type: 'pir_presence',
                    sensor: deviceId,
                    state: state
                });
            }
        }
    } catch (e) {
        console.error('[MQTT] Error:', e);
    }
});