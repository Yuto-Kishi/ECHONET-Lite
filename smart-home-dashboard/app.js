document.addEventListener('DOMContentLoaded', () => {
    const WS_URL = 'ws://localhost:8080';

    setInterval(() => {
        const now = new Date();
        const el = document.getElementById('realtime-clock');
        if (el) el.innerText = "JST " + now.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' });
    }, 1000);

    const sensorState = {};

    // 1. リビング (9分割)
    const livingZones = {
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

    function updateLivingGrid() {
        Object.values(livingZones).forEach(z => z && z.classList.remove('active'));
        const p1 = sensorState['PIR1'],
            p2 = sensorState['PIR2'];
        const p3 = sensorState['PIR3'],
            p4 = sensorState['PIR4'];

        if (p2 && !p1 && !p4) livingZones['north-west'].classList.add('active');
        if (p1 && !p2 && !p3) livingZones['north-east'].classList.add('active');
        if (p4 && !p2 && !p3) livingZones['south-west'].classList.add('active');
        if (p3 && !p1 && !p4) livingZones['south-east'].classList.add('active');

        if (p2 && p1) livingZones['north'].classList.add('active');
        if (p2 && p4) livingZones['west'].classList.add('active');
        if (p1 && p3) livingZones['east'].classList.add('active');
        if (p4 && p3) livingZones['south'].classList.add('active');
        if ((p1 && p4) || (p2 && p3)) livingZones['center'].classList.add('active');
    }

    // 2. その他の部屋
    const roomMapping = {
        'zone-kitchen': ['PIR18'],
        'zone-entrance': ['PIR13'],
        'zone-toilet1': ['PIR11'],
        'zone-washroom': ['PIR5'],
        'zone-japanese-n': ['PIR21'],
        'zone-japanese-s': ['PIR17'],
        'zone-spare': ['PIR6', 'PIR9'],
        'zone-toilet2': ['PIR20'],
        'zone-western2': ['PIR19', 'PIR24'],
        'zone-bed-l': ['PIR22'],
        'zone-bed-r': ['PIR8'],
        'zone-western1': ['PIR10', 'PIR15']
    };

    function updateRooms() {
        for (const [roomId, sensors] of Object.entries(roomMapping)) {
            const roomEl = document.getElementById(roomId);
            if (!roomEl) continue;
            const isActive = sensors.some(id => sensorState[id] === true);
            if (isActive) roomEl.classList.add('active');
            else roomEl.classList.remove('active');
        }
    }

    const socket = new WebSocket(WS_URL);
    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'pir_presence') {
                sensorState[data.sensor] = data.state;
                updateLivingGrid();
                updateRooms();
            }
        } catch (e) { console.error(e); }
    };
});