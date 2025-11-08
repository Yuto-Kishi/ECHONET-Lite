document.addEventListener('DOMContentLoaded', () => {

    // --- 設定 ---
    const WS_URL = 'ws://localhost:8080';
    // ---

    // 1. PIRセンサーの状態
    const sensorState = {
        PIR1: false, // North East
        PIR2: false, // North West
        PIR3: false, // South East
        PIR4: false // South West
    };

    // 2. HTML要素の取得
    // (PIR グリッドゾーン)
    const zones = {
        'north-west': document.getElementById('zone-north-west'),
        'north': document.getElementById('zone-north'),
        'north-east': document.getElementById('zone-north-east'),
        'west': document.getElementById('zone-west'),
        'center': document.getElementById('zone-center'),
        'east': document.getElementById('zone-east'),
        'south-west': document.getElementById('zone-south-west'),
        'south': document.getElementById('zone-south'),
        'south-east': document.getElementById('zone-south-east')
    };

    // (★ M5Stack 環境センサー)
    const aqElements = {
        co2: document.getElementById('val-co2'),
        temp: document.getElementById('val-temp'),
        hum: document.getElementById('val-hum'),
        pm25: document.getElementById('val-pm25'),
        voc: document.getElementById('val-voc'),
        nox: document.getElementById('val-nox'),
        co2Box: document.getElementById('box-co2') // CO2ボックス本体(色付け用)
    };

    // 3. PIR UI 更新関数
    function updatePirUI() {
        Object.values(zones).forEach(zone => zone.classList.remove('active'));

        const pir1 = sensorState.PIR1; // NE
        const pir2 = sensorState.PIR2; // NW
        const pir3 = sensorState.PIR3; // SE
        const pir4 = sensorState.PIR4; // SW

        if (pir2 && !pir1 && !pir4) zones['north-west'].classList.add('active');
        if (pir1 && !pir2 && !pir3) zones['north-east'].classList.add('active');
        if (pir4 && !pir2 && !pir3) zones['south-west'].classList.add('active');
        if (pir3 && !pir1 && !pir4) zones['south-east'].classList.add('active');

        if (pir2 && pir1) zones['north'].classList.add('active');
        if (pir2 && pir4) zones['west'].classList.add('active');
        if (pir1 && pir3) zones['east'].classList.add('active');
        if (pir4 && pir3) zones['south'].classList.add('active');

        if ((pir1 && pir4) || (pir2 && pir3)) zones['center'].classList.add('active');
    }

    // ★ 4. M5Stack UI 更新関数
    function updateAirQualityUI(property, value) {
        switch (property) {
            case 'scd40_co2':
                if (aqElements.co2) aqElements.co2.innerText = value.toFixed(0);
                // CO2レベルで色分け (おまけ)
                if (aqElements.co2Box) {
                    aqElements.co2Box.classList.remove('warn', 'danger');
                    if (value > 1500) {
                        aqElements.co2Box.classList.add('danger');
                    } else if (value > 1000) {
                        aqElements.co2Box.classList.add('warn');
                    }
                }
                break;
            case 'scd40_temp':
                if (aqElements.temp) aqElements.temp.innerText = value.toFixed(1);
                break;
            case 'scd40_hum':
                if (aqElements.hum) aqElements.hum.innerText = value.toFixed(1);
                break;
            case 'sen55_pm2_5':
                if (aqElements.pm25) aqElements.pm25.innerText = value.toFixed(1);
                break;
            case 'sen55_voc':
                if (aqElements.voc) aqElements.voc.innerText = value.toFixed(0);
                break;
            case 'sen55_nox':
                if (aqElements.nox) aqElements.nox.innerText = value.toFixed(0);
                break;

                // M5StackコードにはSEN55の温湿度もあるが、SCD40と重複するため
                // あえてscd40_temp/humのみを使用している。
                // 必要なら 'sen55_temp', 'sen55_hum' の case を追加する
        }
    }


    // 5. WebSocketサーバーに接続
    console.log(`[WS] サーバーに接続中... ${WS_URL}`);
    const socket = new WebSocket(WS_URL);

    socket.onopen = () => console.log('[WS] サーバーに接続しました');
    socket.onclose = () => console.error('[WS] サーバーから切断されました。リロードしてください。');
    socket.onerror = (error) => console.error('[WS] エラー:', error);

    // ★ 6. サーバーからメッセージを受信 (★ ロジック更新)
    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            // server.js から送られてくる 'type' で処理を分岐
            if (data.type === 'pir_presence') {
                // --- PIRセンサーの処理 ---
                if (data.sensor && data.sensor in sensorState) {
                    sensorState[data.sensor] = data.state;
                    updatePirUI(); // PIRのUIを更新
                }
            } else if (data.type === 'air_quality') {
                // --- M5Stackの処理 ---
                updateAirQualityUI(data.property, data.value); // M5StackのUIを更新
            }

        } catch (e) {
            console.error('受信データのパースに失敗:', event.data, e);
        }
    };
});