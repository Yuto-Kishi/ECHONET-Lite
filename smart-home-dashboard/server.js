const express = require('express');
const http = require('http');
const mqtt = require('mqtt');
const { WebSocketServer } = require('ws');

// --- 設定 ---
const MQTT_BROKER = 'mqtt://150.65.179.132:7883';
const CID = '53965d6805152d95';
const HTTP_PORT = 3001;
const WS_PORT = 8080;

// ★ 監視対象デバイス
const DEVICES = [
    // 1F PIR
    'PIR1', 'PIR2', 'PIR3', 'PIR4', 'PIR5', 'PIR11', 'PIR13', 'PIR17', 'PIR18', 'PIR21',
    // 2F PIR
    'PIR6', 'PIR8', 'PIR9', 'PIR10', 'PIR15', 'PIR19', 'PIR20', 'PIR22', 'PIR24',
    // M5Stack
    'M5Stack1', 'M5Stack2', 'M5Stack3', 'M5Stack4', 'M5Stack5', 'M5Stack6', 'M5Stack8', 'M5Stack10',

    // ★★★ 空気清浄機 (8台) ★★★
    'C0A80344-013501', // 洋室1
    'C0A80342-013501', // 洋室2
    'C0A80343-013501', // 主寝室
    'C0A80341-013501', // 和室
    'C0A8033C-013501', // 2Fホール
    'C0A8033E-013501', // 浴室洗面台
    'C0A8033D-013501', // 予備室
    'C0A8033B-013501' // リビング
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

        // PIRセンサー
        if (deviceId.startsWith('PIR')) {
            if (propertyName === 'motion' || propertyName === 'motion_raw') {
                const state = (propertyName === 'motion_raw' ? data.motion_raw : data.motion);
                broadcast({ type: 'pir_presence', sensor: deviceId, state: state });
            }
        }
        // M5Stack
        else if (deviceId.startsWith('M5Stack')) {
            const value = data[propertyName];
            if (value !== undefined) {
                broadcast({ type: 'air_quality', sensor: deviceId, property: propertyName, value: value });
            }
        }
        // ★★★ 家電データ (空気清浄機など) ★★★
        else {
            // 1. データの取り出しを強化
            let value = data[propertyName];

            // もし data["customF1"] が undefined なら、data そのものが中身である可能性が高い
            if (value === undefined) {
                value = data;
            }

            // 2. ログを出力 (サーバーが動いているか確認するため)
            // 空気清浄機からのデータならコンソールに表示
            if (deviceId.includes('013501')) {
                console.log(`[空気清浄機 受信] ID:${deviceId} Prop:${propertyName}`);
                // console.log(JSON.stringify(value)); // 詳細が見たい場合はここを解除
            }

            // 3. 必ずブラウザへ送信
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
        console.error('[MQTT] Error:', e);
    }
});