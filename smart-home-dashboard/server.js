const express = require('express');
const http = require('http');
const mqtt = require('mqtt');
const { WebSocketServer } = require('ws');

// --- 設定 ---
const MQTT_BROKER = 'mqtt://150.65.179.132:7883';
const HTTP_PORT = 3001;
const WS_PORT = 8080;

// ★ 監視対象デバイス (これ以外のIDはブラウザに送らないフィルタ用)
const DEVICES = [
    // 1F PIR
    'PIR1', 'PIR2', 'PIR3', 'PIR4', 'PIR18', 'PIR13', 'PIR11', 'PIR5', 'PIR21', 'PIR17',
    // 2F PIR
    'PIR6', 'PIR8', 'PIR9', 'PIR10', 'PIR15', 'PIR19', 'PIR20', 'PIR22', 'PIR24',
    // M5Stack
    'M5Stack1', 'M5Stack2', 'M5Stack3', 'M5Stack4', 'M5Stack5', 'M5Stack6', 'M5Stack8', 'M5Stack10',

    // 空気清浄機 (8台)
    'C0A80344-013501', 'C0A80342-013501', 'C0A80343-013501', 'C0A80341-013501',
    'C0A8033C-013501', 'C0A8033E-013501', 'C0A8033D-013501', 'C0A8033B-013501',

    // エアコン (2台)
    'C0A80368-013001', 'C0A80367-013001'
];

// --- サーバーセットアップ ---
const app = express();
app.use(express.static(__dirname));
const server = http.createServer(app);
server.listen(HTTP_PORT, () => { console.log(`[HTTP] サーバー起動: http://localhost:${HTTP_PORT}`); });

const wss = new WebSocketServer({ port: WS_PORT });
console.log(`[WS] WebSocketサーバー起動: ws://localhost:${WS_PORT}`);

function broadcast(data) {
    const jsonData = JSON.stringify(data);
    wss.clients.forEach(client => { if (client.readyState === 1) client.send(jsonData); });
}

// --- MQTTクライアント ---
const mqttClient = mqtt.connect(MQTT_BROKER);

mqttClient.on('connect', () => {
    console.log(`[MQTT] 接続成功: ${MQTT_BROKER}`);
    // ★重要: 全てのトピックを購読して取りこぼしを防ぐ
    mqttClient.subscribe('/server/#');
    console.log(`[MQTT] 全トピック監視開始 (/server/#)`);
});

mqttClient.on('message', (topic, payload) => {
    try {
        // トピック分解: /server/CID/DeviceID/properties/PropName
        const parts = topic.split('/');
        // parts[0]='', parts[1]='server', parts[2]=CID, parts[3]=DeviceID
        if (parts.length < 6) return;

        const deviceId = parts[3];
        const propertyName = parts[5];

        // 監視リストにないデバイスは無視
        if (!DEVICES.includes(deviceId)) return;

        const data = JSON.parse(payload.toString());

        // --- ログ出力 (デバッグ用: 家電データが来たら表示) ---
        if (deviceId.startsWith('C0A8')) {
            // console.log(`[受信] ${deviceId} ${propertyName}`); // 多すぎる場合はコメントアウト
        }

        // === 1. PIRセンサー ===
        if (deviceId.startsWith('PIR')) {
            // motion または motion_raw を処理
            if (propertyName.includes('motion')) {
                const state = (data.motion_raw !== undefined) ? data.motion_raw : data.motion;
                broadcast({ type: 'pir_presence', sensor: deviceId, state: state });
            }
        }
        // === 2. M5Stack ===
        else if (deviceId.startsWith('M5Stack')) {
            const value = data[propertyName];
            if (value !== undefined) {
                broadcast({ type: 'air_quality', sensor: deviceId, property: propertyName, value: value });
            }
        }
        // === 3. 家電 (エアコン・空気清浄機) ===
        else {
            let value = data[propertyName];
            // customF1などの場合、データの中身にキーがなく、ペイロード全体が値の場合がある
            if (value === undefined) value = data;

            if (value !== undefined) {
                broadcast({
                    type: 'appliance_data',
                    deviceId: deviceId,
                    property: propertyName,
                    value: value
                });
            }
        }
    } catch (e) {
        // console.error('[MQTT] Parse Error:', e);
    }
});