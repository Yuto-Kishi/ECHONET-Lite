const express = require('express');
const http = require('http');
const mqtt = require('mqtt');
const { WebSocketServer } = require('ws');

// --- 設定 ---
// 学内ネットワーク等の場合
const MQTT_BROKER = 'mqtt://150.65.179.132:1883';

// ★ここを 3030 に変更しました
const HTTP_PORT = 8030; 
// ★ここも念の為 8081 に変更しました（重複回避）
const WS_PORT = 8081;   

// ★ 監視対象デバイス
const TARGET_DEVICE = 'C0A8033B-013501';

// --- サーバーセットアップ ---
const app = express();
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
console.log(`[MQTT] 接続試行中: ${MQTT_BROKER}...`);
const mqttClient = mqtt.connect(MQTT_BROKER);

mqttClient.on('connect', () => {
    console.log(`[MQTT] 接続成功!`);
    mqttClient.subscribe('/server/#');
    console.log(`[MQTT] ターゲット監視開始: ${TARGET_DEVICE}`);
});

mqttClient.on('error', (err) => {
    console.error(`[MQTT] エラー発生: ${err.message}`);
});

mqttClient.on('message', (topic, payload) => {
    try {
        const parts = topic.split('/');
        if (parts.length < 6) return;

        const deviceId = parts[3];
        const propertyName = parts[5];

        if (deviceId !== TARGET_DEVICE) return;

        const payloadStr = payload.toString();
        const data = JSON.parse(payloadStr);

        console.log(`[受信] ${propertyName}:`, data);

        let value = data[propertyName];
        if (value === undefined) value = data;

        if (value !== undefined) {
            broadcast({
                type: 'appliance_data',
                deviceId: deviceId,
                property: propertyName,
                value: value
            });
        }
    } catch (e) {
        console.error('[MQTT] Parse Error:', e);
    }
});