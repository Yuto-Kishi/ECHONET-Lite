// mqtt_to_es.js
//
// MQTTブローカーからスマートホームのデータ（PIR / M5Stack / 空気清浄機 / エアコン）を購読し、
// Elasticsearch の "smart-home-events" インデックスに書き込み続けるスクリプト。

const mqtt = require('mqtt');
const { Client } = require('@elastic/elasticsearch');

// ===== 設定 =====

// MQTT ブローカー
const MQTT_BROKER_URL = process.env.MQTT_BROKER_URL || 'mqtt://150.65.179.132:7883';
const MQTT_TOPIC = process.env.MQTT_TOPIC || '/server/#'; // 全部拾ってあとでフィルタ

// Elasticsearch
// docker-compose 内からなら "http://elasticsearch:9200"
// ホストから直接動かすなら "http://localhost:9200"
const ES_NODE = process.env.ES_NODE || 'http://elasticsearch:9200';
const ES_INDEX = process.env.ES_INDEX || 'smart-home-events';

// ログの出方制御
const LOG_EVERY_N_MESSAGES = 50;

// デバイス種別判定
function inferDeviceType(deviceId) {
    if (!deviceId) return 'unknown';
    if (deviceId.startsWith('PIR')) return 'pir';
    if (deviceId.startsWith('M5Stack')) return 'm5stack';
    if (deviceId.includes('013501')) return 'air_purifier'; // 空気清浄機
    if (deviceId.includes('013001')) return 'aircon'; // エアコン
    return 'other';
}

// Elasticsearch クライアント
const esClient = new Client({ node: ES_NODE });

// MQTT クライアント
console.log('[MQTT→ES] Connecting to MQTT broker:', MQTT_BROKER_URL);
const mqttClient = mqtt.connect(MQTT_BROKER_URL);

let msgCount = 0;

mqttClient.on('connect', () => {
    console.log('[MQTT→ES] Connected to MQTT broker');
    mqttClient.subscribe(MQTT_TOPIC, (err) => {
        if (err) {
            console.error('[MQTT→ES] Failed to subscribe:', err);
        } else {
            console.log(`[MQTT→ES] Subscribed to topic: ${MQTT_TOPIC}`);
        }
    });
});

mqttClient.on('error', (err) => {
    console.error('[MQTT→ES] MQTT error:', err);
});

// メイン: メッセージを受信するたびに Elasticsearch に書き込む
mqttClient.on('message', async(topic, payloadBuffer) => {
    msgCount++;

    const payloadStr = payloadBuffer.toString();
    let payload;
    try {
        payload = JSON.parse(payloadStr);
    } catch (e) {
        // JSON じゃない場合も一応保存できるようにしておく
        payload = { _raw: payloadStr };
    }

    // topic 例: /server/{CID}/{deviceId}/properties/{propertyName}
    const parts = topic.split('/');
    // ['', 'server', '{CID}', '{deviceId}', 'properties', '{propertyName}']
    if (parts.length < 6 || parts[1] !== 'server') {
        // 想定外のトピックは一旦無視
        return;
    }

    const cid = parts[2];
    const deviceId = parts[3];
    const propertyName = parts[5];
    const deviceType = inferDeviceType(deviceId);

    // PIR / M5Stack / 空気清浄機 / エアコン 以外は今回はスキップしてもよい（必要なら other も保存可）
    const allowedTypes = ['pir', 'm5stack', 'air_purifier', 'aircon'];
    if (!allowedTypes.includes(deviceType)) {
        return;
    }

    // 1件の MQTT メッセージ = 1件の ES ドキュメント として保存
    const doc = {
        '@timestamp': new Date().toISOString(), // Kibana での時系列表示用
        topic,
        cid,
        deviceId,
        deviceType,
        property: propertyName,
        payload // 元の JSON 全部
    };

    // 代表値を value として抜き出しておくと Kibana で扱いやすい
    // 例: { "co2": 400 } → value=400
    //     { "outsideTemperature": 25.7, "humanDetected": false, ... } → value: null
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
        const keys = Object.keys(payload);
        if (keys.length === 1 && typeof payload[keys[0]] !== 'object') {
            doc.valueKey = keys[0];
            doc.value = payload[keys[0]];
        } else if (payload._raw !== undefined) {
            // _raw の場合はそのまま
            doc.valueKey = '_raw';
            doc.value = payload._raw;
        } else {
            doc.value = null;
        }
    } else {
        doc.value = null;
    }

    try {
        await esClient.index({
            index: ES_INDEX,
            body: doc
        });

        if (msgCount % LOG_EVERY_N_MESSAGES === 0) {
            console.log(`[MQTT→ES] Inserted ${msgCount} documents (last: ${deviceType} ${deviceId} ${propertyName})`);
        }
    } catch (e) {
        console.error('[MQTT→ES] Elasticsearch index error:', e.meta && e.meta.body ? e.meta.body : e);
    }
});

process.on('SIGINT', () => {
    console.log('\n[MQTT→ES] Shutting down...');
    mqttClient.end();
    process.exit(0);
});