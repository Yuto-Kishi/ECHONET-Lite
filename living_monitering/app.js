document.addEventListener('DOMContentLoaded', () => {

    // --- 設定 ---
    const WS_URL = 'ws://localhost:8080';
    // ---

    // 1. センサーの現在の状態を保持するオブジェクト
    const sensorState = {
        PIR1: false, // North East
        PIR2: false, // North West
        PIR3: false, // South East
        PIR4: false // South West
    };

    // 2. 各ゾーンのHTML要素をあらかじめ取得
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

    // 3. UIを更新する関数（ロジックの肝）
    function updateUI() {
        // 全てのゾーンから 'active' クラスを一旦削除
        Object.values(zones).forEach(zone => {
            zone.classList.remove('active');
        });

        const pir1 = sensorState.PIR1; // North East
        const pir2 = sensorState.PIR2; // North West
        const pir3 = sensorState.PIR3; // South East
        const pir4 = sensorState.PIR4; // South West

        // ゾーンの活性化ロジック
        // イメージ画像とセンサー配置を参考に定義します

        // 単独センサーが反応しているゾーン
        if (pir2 && !pir1 && !pir4) zones['north-west'].classList.add('active');
        if (pir1 && !pir2 && !pir3) zones['north-east'].classList.add('active');
        if (pir4 && !pir2 && !pir3) zones['south-west'].classList.add('active');
        if (pir3 && !pir1 && !pir4) zones['south-east'].classList.add('active');

        // 複合センサーが反応しているゾーン (隣接するセンサーの組み合わせ)
        if (pir2 && pir1) zones['north'].classList.add('active'); // PIR2(NW) & PIR1(NE)
        if (pir2 && pir4) zones['west'].classList.add('active'); // PIR2(NW) & PIR4(SW)
        if (pir1 && pir3) zones['east'].classList.add('active'); // PIR1(NE) & PIR3(SE)
        if (pir4 && pir3) zones['south'].classList.add('active'); // PIR4(SW) & PIR3(SE)

        // 中央 (4つのPIRのうち少なくとも2つ以上、または3つ、4つが反応した場合など)
        // ここはロジックをどう定義するかで変わります。
        // 例: 4つ全て反応したら中央をアクティブ
        // if (pir1 && pir2 && pir3 && pir4) zones['center'].classList.add('active');
        // 例: 対角線が反応したら中央をアクティブ
        if ((pir1 && pir4) || (pir2 && pir3)) zones['center'].classList.add('active');
        // 例: いずれかのPIRが反応している中で、さらに2つ以上が反応したら中央をアクティブ (より複雑なロジック)
        // const activeCount = [pir1, pir2, pir3, pir4].filter(Boolean).length;
        // if (activeCount >= 2 && !zones['north-west'].classList.contains('active') && ...他の単独/複合ゾーンがアクティブでなければ) {
        //     zones['center'].classList.add('active');
        // }
    }

    // 4. WebSocketサーバーに接続
    console.log(`[WS] サーバーに接続中... ${WS_URL}`);
    const socket = new WebSocket(WS_URL);

    socket.onopen = () => {
        console.log('[WS] サーバーに接続しました');
    };

    socket.onclose = () => {
        console.error('[WS] サーバーから切断されました。リロードしてください。');
        // 必要に応じて再接続処理をここに追加
    };

    socket.onerror = (error) => {
        console.error('[WS] エラー:', error);
    };

    // 5. サーバーからメッセージを受信したときの処理
    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            if (data.sensor && data.sensor in sensorState) {
                // センサーの状態を更新
                sensorState[data.sensor] = data.state;

                // UIを再描画
                updateUI();
            }
        } catch (e) {
            console.error('受信データのパースに失敗:', event.data, e);
        }
    };
});