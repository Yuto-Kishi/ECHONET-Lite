document.addEventListener('DOMContentLoaded', () => {
    const WS_URL = 'ws://localhost:8080';

    setInterval(() => {
        const now = new Date();
        const el = document.getElementById('realtime-clock');
        if (el) el.innerText = "JST " + now.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' });
    }, 1000);

    const latestEnvData = {};
    const applianceData = {};
    let activePIRId = null;
    let activeAppId = null;

    const sensorToEnvMap = {
        'PIR1': 'M5Stack2',
        'PIR2': 'M5Stack2',
        'PIR3': 'M5Stack2',
        'PIR4': 'M5Stack2',
        'PIR18': 'M5Stack8',
        'PIR5': 'M5Stack3',
        'PIR21': 'M5Stack1',
        'PIR17': 'M5Stack1',
        'PIR6': 'M5Stack4',
        'PIR9': 'M5Stack4',
        'PIR19': 'M5Stack5',
        'PIR24': 'M5Stack5',
        'PIR22': 'M5Stack6',
        'PIR8': 'M5Stack6',
        'PIR15': 'M5Stack10',
        'PIR10': 'M5Stack10'
    };

    const tooltip = document.getElementById('env-tooltip');

    function showTooltip(title, contentHTML) {
        let html = `<div style="border-bottom:2px solid #888; margin-bottom:5px; color:#555; font-size:1.1em; font-weight:bold;">${title}</div>`;
        html += contentHTML;
        tooltip.innerHTML = html;
        tooltip.style.display = 'block';
    }

    // --- M5Stack用 ---
    function renderEnvTooltip(pirId) {
        const envId = sensorToEnvMap[pirId];
        if (!envId) return;
        const data = latestEnvData[envId];
        let body = "";
        if (!data || Object.keys(data).length === 0) {
            body = `<div style="color:#999;">データ受信待ち...</div>`;
        } else {
            if (data.temp) body += `<div class="tooltip-row"><span class="tooltip-label">温度</span><span class="tooltip-val">${data.temp}℃</span></div>`;
            if (data.hum) body += `<div class="tooltip-row"><span class="tooltip-label">湿度</span><span class="tooltip-val">${data.hum}%</span></div>`;
            if (data.co2) body += `<div class="tooltip-row"><span class="tooltip-label">CO2</span><span class="tooltip-val">${data.co2}ppm</span></div>`;
            if (data.voc) body += `<div class="tooltip-row"><span class="tooltip-label">VOC</span><span class="tooltip-val">${data.voc}</span></div>`;
            if (data.pm25) body += `<div class="tooltip-row"><span class="tooltip-label">PM2.5</span><span class="tooltip-val">${data.pm25}µg</span></div>`;
        }
        showTooltip(envId, body);
    }

    // --- 家電用 (エアコン・空清) ---
    function renderAppTooltip(appId) {
        const data = applianceData[appId] || {};
        let body = "";

        if (Object.keys(data).length === 0) {
            body = `<div style="color:#999;">データ受信待ち...</div>`;
        } else {
            // 電源
            if (data.operationStatus !== undefined) {
                const opStatus = data.operationStatus ? '<span style="color:#28a745;">ON</span>' : '<span style="color:#aaa;">OFF</span>';
                body += `<div class="tooltip-row"><span class="tooltip-label">電源</span><span class="tooltip-val">${opStatus}</span></div>`;
            }

            // --- 共通・空気清浄機 ---
            const temp = data.temperature || data.roomTemperature;
            if (temp !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">室温</span><span class="tooltip-val">${temp}℃</span></div>`;
            if (data.humidity !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">湿度</span><span class="tooltip-val">${data.humidity}%</span></div>`;

            if (data.dustValue !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">ホコリ</span><span class="tooltip-val">${data.dustValue}</span></div>`;
            if (data.illuminanceValue !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">照度</span><span class="tooltip-val">${data.illuminanceValue}lx</span></div>`;
            if (data.instantaneousElectricPowerConsumption !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">電力</span><span class="tooltip-val">${data.instantaneousElectricPowerConsumption}W</span></div>`;
            if (data.airFlowLevel !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">風量</span><span class="tooltip-val">${data.airFlowLevel}</span></div>`;

            if (data.pm25 !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">PM2.5</span><span class="tooltip-val">${data.pm25}µg</span></div>`;
            if (data.gasContaminationValue !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">ガス</span><span class="tooltip-val">${data.gasContaminationValue}</span></div>`;

            // --- エアコン特有 ---
            if (data.outsideTemperature !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">外気温</span><span class="tooltip-val">${data.outsideTemperature}℃</span></div>`;
            if (data.humanDetected !== undefined) {
                const human = data.humanDetected ? '<span style="color:#ff007c;">あり</span>' : 'なし';
                body += `<div class="tooltip-row"><span class="tooltip-label">人検知</span><span class="tooltip-val">${human}</span></div>`;
            }
            if (data.blowingOutAirTemperature !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">吹出温度</span><span class="tooltip-val">${data.blowingOutAirTemperature}℃</span></div>`;

            // ★★★ 修正: 日射センサー (数値をそのまま表示) ★★★
            if (data.sunshineSensorData !== undefined) {
                body += `<div class="tooltip-row"><span class="tooltip-label">日射</span><span class="tooltip-val">${data.sunshineSensorData}</span></div>`;
            }

            if (data.co2Concentration !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">CO2</span><span class="tooltip-val">${data.co2Concentration}ppm</span></div>`;

            // 設定温度
            const setTemp = data.setTemperature || data.targetTemperature;
            if (setTemp !== undefined) body += `<div class="tooltip-row"><span class="tooltip-label">設定</span><span class="tooltip-val">${setTemp}℃</span></div>`;

            // モード
            if (data.operationMode) body += `<div class="tooltip-row"><span class="tooltip-label">モード</span><span class="tooltip-val">${data.operationMode}</span></div>`;
        }
        showTooltip(appId, body);
    }

    document.querySelectorAll('.pir-dot').forEach(dot => {
        const pirId = dot.id.replace('dot-', '');
        dot.addEventListener('mouseenter', () => {
            if (sensorToEnvMap[pirId]) {
                activePIRId = pirId;
                renderEnvTooltip(pirId);
            }
        });
        dot.addEventListener('mousemove', (e) => {
            if (activePIRId) {
                tooltip.style.top = (e.clientY + 15) + 'px';
                tooltip.style.left = (e.clientX + 15) + 'px';
            }
        });
        dot.addEventListener('mouseleave', () => {
            activePIRId = null;
            tooltip.style.display = 'none';
        });
    });

    document.querySelectorAll('.appliance-icon').forEach(icon => {
        const appId = icon.id.replace('app-', '');
        icon.addEventListener('mouseenter', () => {
            activeAppId = appId;
            renderAppTooltip(appId);
        });
        icon.addEventListener('mousemove', (e) => {
            tooltip.style.top = (e.clientY + 15) + 'px';
            tooltip.style.left = (e.clientX + 15) + 'px';
        });
        icon.addEventListener('mouseleave', () => {
            activeAppId = null;
            tooltip.style.display = 'none';
        });
    });

    const socket = new WebSocket(WS_URL);
    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            if (data.type === 'pir_presence') {
                const dot = document.getElementById(`dot-${data.sensor}`);
                if (dot) data.state ? dot.classList.add('active') : dot.classList.remove('active');
            } else if (data.type === 'air_quality') {
                if (data.sensor) updateEnvData(data.sensor, data.property, data.value);
            } else if (data.type === 'appliance_data') {
                if (!applianceData[data.deviceId]) applianceData[data.deviceId] = {};
                if (typeof data.value === 'object') Object.assign(applianceData[data.deviceId], data.value);
                else applianceData[data.deviceId][data.property] = data.value;

                if (data.property === 'operationStatus' || applianceData[data.deviceId].operationStatus !== undefined) {
                    const icon = document.getElementById(`app-${data.deviceId}`);
                    if (icon) {
                        const isOn = applianceData[data.deviceId].operationStatus;
                        isOn ? icon.classList.add('active') : icon.classList.remove('active');
                    }
                }
                if (activeAppId === data.deviceId) renderAppTooltip(activeAppId);
            }
        } catch (e) { console.error(e); }
    };

    function updateEnvData(deviceId, property, value) {
        if (!latestEnvData[deviceId]) latestEnvData[deviceId] = {};
        let type = '';
        if (property.includes('co2')) type = 'co2';
        else if (property.includes('temp')) type = 'temp';
        else if (property.includes('hum')) type = 'hum';
        else if (property.includes('pm2_5')) type = 'pm25';
        else if (property.includes('voc')) type = 'voc';

        if (type) {
            const val = (typeof value === 'number') ? value.toFixed(type === 'co2' || type === 'voc' ? 0 : 1) : value;
            latestEnvData[deviceId][type] = val;
            if (activePIRId && sensorToEnvMap[activePIRId] === deviceId) renderEnvTooltip(activePIRId);
        }
    }
});