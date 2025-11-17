document.addEventListener('DOMContentLoaded', () => {

    // --- 設定 ---
    const WS_URL = 'ws://localhost:8080';
    // ★ グラフ関連の定数を削除
    // ---

    // --- リアルタイム時計 ---
    const clockElement = document.getElementById('realtime-clock');

    function updateClock() {
        if (!clockElement) return; // 要素がなければ何もしない

        const now = new Date();
        // 'ja-JP'ロケールと'Asia/Tokyo'タイムゾーンでフォーマット
        const options = {
            timeZone: 'Asia/Tokyo',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false // 24時間表記
        };

        try {
            clockElement.innerText = "JST " + now.toLocaleString('ja-JP', options);
        } catch (e) {
            clockElement.innerText = now.toLocaleString(); // フォールバック
        }
    }
    // 1秒ごとに時計を更新
    setInterval(updateClock, 1000);
    // 最初に一回実行
    updateClock();


    // 1. PIRセンサーの状態
    const sensorState = {
        PIR1: false,
        PIR2: false,
        PIR3: false,
        PIR4: false
    };

    // 2. HTML要素の取得 (PIR グリッドゾーン)
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

    // 3. HTML要素の取得 (M5Stack 環境センサー)
    const aqElements = {
        co2: document.getElementById('val-co2'),
        temp: document.getElementById('val-temp'),
        hum: document.getElementById('val-hum'),
        pm25: document.getElementById('val-pm25'),
        voc: document.getElementById('val-voc'),
        nox: document.getElementById('val-nox'),
        co2Box: document.getElementById('box-co2')
    };

    // ★ 4. チャート用の変数を削除
    // ★ 5. グラフを初期化する関数を削除
    // ★ 6. 5つのチャートのインスタンスを作成する処理を削除

    // 7. PIR UI 更新関数
    function updatePirUI() {
        Object.values(zones).forEach(zone => zone.classList.remove('active'));
        const { PIR1: pir1, PIR2: pir2, PIR3: pir3, PIR4: pir4 } = sensorState;

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

    // 8. M5Stack UI 更新関数 (テキスト表示のみ)
    function updateAirQualityUI(property, value) {
        // 常に最新の値を表示
        switch (property) {
            case 'scd40_co2':
                if (aqElements.co2) aqElements.co2.innerText = value.toFixed(0);
                if (aqElements.co2Box) {
                    aqElements.co2Box.classList.remove('warn', 'danger');
                    if (value > 1500) aqElements.co2Box.classList.add('danger');
                    else if (value > 1000) aqElements.co2Box.classList.add('warn');
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
        }
    }

    // ★ 9. 1分ごとにデータを集約する関数とタイマーを削除

    // 10. WebSocketサーバーに接続
    console.log(`[WS] サーバーに接続中... ${WS_URL}`);
    const socket = new WebSocket(WS_URL);

    socket.onopen = () => console.log('[WS] サーバーに接続しました');
    socket.onclose = () => console.error('[WS] サーバーから切断されました。リロードしてください。');
    socket.onerror = (error) => console.error('[WS] エラー:', error);

    // ★ 11. サーバーからメッセージを受信 (★ ロジックを簡素化)
    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            if (data.type === 'pir_presence') {
                // --- PIRの処理 ---
                if (data.sensor && data.sensor in sensorState) {
                    sensorState[data.sensor] = data.state;
                    updatePirUI();
                }
            } else if (data.type === 'air_quality') {
                // --- M5Stackの処理 ---
                // (1) 最新の値をテキストボックスに表示
                updateAirQualityUI(data.property, data.value);

                // (2) グラフ用のバッファ処理を削除
            }

        } catch (e) {
            console.error('受信データのパースに失敗:', event.data, e);
        }
    };
});