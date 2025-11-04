const express = require('express');
const http = require('http');
const mqtt = require('mqtt');
const { WebSocketServer } = require('ws');

// --- 設定 ---
const MQTT_BROKER = 'mqtt://150.65.179.132:7883';
const CID = '53965d6805152d95'; // ESP32コードと共通
const SENSORS = ['PIR1', 'PIR2', 'PIR3', 'PIR4'];
const TOPIC_PREFIX = `/server/${CID}/`;
const TOPIC_SUFFIX = '/properties/motion_raw';

const HTTP_PORT = 3000; // ブラウザでアクセスするポート
const WS_PORT = 8080; // WebSocket通信用のポート
// ---

// 1. HTTPサーバーのセットアップ (HTML/CSS/JSを配信)
const app = express();
app.use(express.static(__dirname)); // このフォルダ内のファイル(index.htmlなど)を配信
const server = http.createServer(app);
server.listen(HTTP_PORT, () => {
    console.log(`[HTTP] サーバー起動: http://localhost:${HTTP_PORT}`);
});

// 2. WebSocketサーバーのセットアップ
const wss = new WebSocketServer({ port: WS_PORT });
console.log(`[WS] WebSocketサーバー起動: ws://localhost:${WS_PORT}`);

wss.on('connection', ws => {
    console.log('[WS] クライアントが接続しました');
    ws.on('close', () => console.log('[WS] クライアント接続が切れました'));
});

// 全クライアントにブロードキャストする関数
function broadcast(data) {
    const jsonData = JSON.stringify(data);
    wss.clients.forEach(client => {
        if (client.readyState === 1) { // 1 = OPEN
            client.send(jsonData);
        }
    });
}

// 3. MQTTクライアントのセットアップ
const mqttClient = mqtt.connect(MQTT_BROKER);

mqttClient.on('connect', () => {
    console.log(`[MQTT] ブローカーに接続しました: ${MQTT_BROKER}`);
    // 全センサーのトピックを購読
    SENSORS.forEach(sensorId => {
        const topic = `${TOPIC_PREFIX}${sensorId}${TOPIC_SUFFIX}`;
        mqttClient.subscribe(topic, err => {
            if (!err) {
                console.log(`[MQTT] 購読開始: ${topic}`);
            }
        });
    });
});

// MQTTメッセージ受信時の処理
mqttClient.on('message', (topic, payload) => {
    try {
        // トピックからセンサーIDを抽出
        // 例: /server/CID/PIR1/properties/motion_raw -> PIR1
        const parts = topic.split('/');
        const sensorId = parts[3]; // CIDの次

        if (SENSORS.includes(sensorId)) {
            const data = JSON.parse(payload.toString());
            const state = data.motion_raw; // ESP32コードの `j["motion_raw"]` に対応

            console.log(`[MQTT] 受信: ${sensorId} -> ${state}`);

            // WebSocketでブラウザにブロードキャスト
            broadcast({
                sensor: sensorId,
                state: state
            });
        }
    } catch (e) {
        console.error('[MQTT] メッセージのパースに失敗:', e.message);
    }
});

mqttClient.on('error', err => {
    console.error('[MQTT] エラー:', err);
});