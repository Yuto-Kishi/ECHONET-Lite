document.addEventListener('DOMContentLoaded', () => {

    // --- 設定 ---
    const WS_URL = 'ws://localhost:8080';
    const AGGREGATE_INTERVAL = 60 * 1000; // 60秒 (1分) ごとにデータを集約
    const MAX_DATA_POINTS = 12 * 60; // 12時間 * 60分 = 720データポイント
    // ---

    // ★★★ リアルタイム時計 (ここから追加) ★★★
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
    // ★★★ (ここまで追加) ★★★


    // 1. PIRセンサーの状態
    const sensorState = {
        PIR1: false,
        PIR2: false,
        PIR3: false,
        PIR4: false
    };

    // 2. HTML要素の取得 (PIR グリッドゾーン)
    // ... (以下、変更なし) ...
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

    // 4. チャート用の変数
    const charts = {}; // 5つのチャートインスタンスを保持
    const tempDataBuffer = {
        co2: [],
        temp: [],
        hum: [],
        pm25: [],
        voc: []
    };

    // 5. グラフを初期化する関数
    function createChart(ctx, label, borderColor) {
        return new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [{
                    label: label,
                    data: [], // {x: Date, y: value} の形式で入る
                    borderColor: borderColor,
                    backgroundColor: borderColor + '33',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                }]
            },
            options: {
                scales: {
                    x: {
                        type: 'time', // X軸を「時刻」に設定
                        time: {
                            unit: 'hour', // 1時間単位でラベル表示
                            tooltipFormat: 'HH:mm', // ツールチップの時刻フォーマット
                            displayFormats: {
                                hour: 'HH:mm'
                            }
                        },
                        ticks: {
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 12 // X軸のラベルを最大12個に
                        }
                    },
                    y: {
                        beginAtZero: false
                    }
                },
                plugins: {
                    legend: { display: true }
                },
                animation: { duration: 0 } // リアルタイム更新のためアニメーションOFF
            }
        });
    }

    // 6. 5つのチャートのインスタンスを作成
    const co2Ctx = document.getElementById('co2Chart');
    if (co2Ctx) charts.co2 = createChart(co2Ctx, 'CO2 (ppm)', '#9b01b6');

    const tempCtx = document.getElementById('tempChart');
    if (tempCtx) charts.temp = createChart(tempCtx, '温度 (°C)', '#007bff');

    const humCtx = document.getElementById('humChart');
    if (humCtx) charts.hum = createChart(humCtx, '湿度 (%)', '#17a2b8');

    const pm25Ctx = document.getElementById('pm25Chart');
    if (pm25Ctx) charts.pm25 = createChart(pm25Ctx, 'PM2.5 (µg/m³)', '#6c757d');

    const vocCtx = document.getElementById('vocChart');
    if (vocCtx) charts.voc = createChart(vocCtx, 'VOC Index', '#fd7e14');


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

    // 8. M5Stack UI 更新関数
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

    // 9. 1分ごとにデータを集約してグラフにプッシュする関数
    function aggregateAndPushData() {
        const now = new Date(); // 集約した時刻

        for (const key in tempDataBuffer) {
            const buffer = tempDataBuffer[key];
            const chart = charts[key];

            if (buffer.length > 0 && chart) {
                // 1分間の平均値を計算
                const sum = buffer.reduce((a, b) => a + b, 0);
                const avg = sum / buffer.length;

                // グラフのデータセットを取得
                const dataset = chart.data.datasets[0].data;

                // 新しいデータを追加
                dataset.push({ x: now, y: avg });

                // データが12時間分 (720件) を超えたら古いものを削除
                while (dataset.length > MAX_DATA_POINTS) {
                    dataset.shift();
                }

                // バッファをクリア
                tempDataBuffer[key] = [];

                // グラフを更新
                chart.update();
            }
        }
    }

    // 1分ごとに集約関数を実行するタイマーをセット
    setInterval(aggregateAndPushData, AGGREGATE_INTERVAL);


    // 10. WebSocketサーバーに接続
    console.log(`[WS] サーバーに接続中... ${WS_URL}`);
    const socket = new WebSocket(WS_URL);

    socket.onopen = () => console.log('[WS] サーバーに接続しました');
    socket.onclose = () => console.error('[WS] サーバーから切断されました。リロードしてください。');
    socket.onerror = (error) => console.error('[WS] エラー:', error);

    // 11. サーバーからメッセージを受信
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

                // (2) グラフ用のデータを一時バッファに溜める
                switch (data.property) {
                    case 'scd40_co2':
                        tempDataBuffer.co2.push(data.value);
                        break;
                    case 'scd40_temp':
                        tempDataBuffer.temp.push(data.value);
                        break;
                    case 'scd40_hum':
                        tempDataBuffer.hum.push(data.value);
                        break;
                    case 'sen55_pm2_5':
                        tempDataBuffer.pm25.push(data.value);
                        break;
                    case 'sen55_voc':
                        tempDataBuffer.voc.push(data.value);
                        break;
                }
            }

        } catch (e) {
            console.error('受信データのパースに失敗:', event.data, e);
        }
    };
});