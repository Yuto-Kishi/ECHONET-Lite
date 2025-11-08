const express = require('express');
const http = require('http');
const mqtt = require('mqtt');
const { WebSocketServer } = require('ws');

// --- 設定 ---
const MQTT_BROKER = 'mqtt://150.65.179.132:7883';
const CID = '53965d6805152d95'; // ESP32/M5Stackコードと共通
const HTTP_PORT = 3001; // 3000が使用中だったため 3001 に変更
const WS_PORT = 8080; // WebSocket通信用のポート

// ★ 監視対象のデバイスリスト (PIR + M5Stack)
const DEVICES = ['PIR1', 'PIR2', 'PIR3', 'PIR4', 'M5Stack2'];

// --- 1. HTTPサーバーのセットアップ ---
const app = express();
app.use(express.static(__dirname));
const server = http.createServer(app);
server.listen(HTTP_PORT, () => {
    console.log(`[HTTP] サーバー起動: http://localhost:${HTTP_PORT}`);
});

// --- 2. WebSocketサーバーのセットアップ ---
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

// --- 3. MQTTクライアントのセットアップ ---
const mqttClient = mqtt.connect(MQTT_BROKER);

mqttClient.on('connect', () => {
    console.log(`[MQTT] ブローカーに接続しました: ${MQTT_BROKER}`);

    // ★ 全デバイスの全プロパティを購読
    DEVICES.forEach(deviceId => {
        // トピック例: /server/CID/PIR1/properties/+
        //           /server/CID/M5Stack2/properties/+
        // '+' はシングルレベルのワイルドカード
        const topic = `/server/${CID}/${deviceId}/properties/+`;
        mqttClient.subscribe(topic, err => {
            if (!err) {
                console.log(`[MQTT] 購読開始: ${topic}`);
            } else {
                console.error(`[MQTT] 購読失敗: ${topic}`, err);
            }
        });
    });
});

// --- 4. MQTTメッセージ受信時の処理 (★ ロジック更新) ---
mqttClient.on('message', (topic, payload) => {
    try {
        const parts = topic.split('/');
        // parts[0] = ""
        // parts[1] = "server"
        // parts[2] = CID
        // parts[3] = deviceId (例: "PIR1" や "M5Stack2")
        // parts[4] = "properties"
        // parts[5] = propertyName (例: "motion_raw" や "scd40_co2")

        if (parts.length < 6) return; // 不正なトピックは無視

        const deviceId = parts[3];
        const propertyName = parts[5];

        if (!DEVICES.includes(deviceId)) return; // 監視対象外のデバイスは無視

        const data = JSON.parse(payload.toString());

        // ★ デバイスID (PIRかM5Stackか) で処理を分岐
        if (deviceId.startsWith('PIR')) {
            // --- PIRセンサーの処理 ---
            if (propertyName === 'motion_raw') {
                const state = data.motion_raw;
                console.log(`[MQTT] 受信 (PIR): ${deviceId} -> ${state}`);

                // ブラウザにPIR用のデータを送信
                broadcast({
                    type: 'pir_presence', // ★タイプを追加
                    sensor: deviceId,
                    state: state
                });
            }
        } else if (deviceId === 'M5Stack2') {
            // --- M5Stackの処理 ---
            // data オブジェクトから値を取得 (例: {"scd40_co2": 450})
            const value = data[propertyName];

            if (value !== undefined) {
                console.log(`[MQTT] 受信 (M5Stack): ${propertyName} -> ${value}`);

                // ブラウザに環境センサー用のデータを送信
                broadcast({
                    type: 'air_quality', // ★タイプを追加
                    property: propertyName,
                    value: value
                });
            }
        }

    } catch (e) {
        console.error('[MQTT] メッセージのパースに失敗:', e.message, payload.toString());
    }
});

mqttClient.on('error', err => {
    console.error('[MQTT] エラー:', err);
});