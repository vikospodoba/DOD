const characterSelect = document.getElementById("characterSelect");
const manyFacesToggle = document.getElementById("manyFacesToggle");
const startButton = document.getElementById("startButton");
const stopButton = document.getElementById("stopButton");
const statusEl = document.getElementById("status");
const fpsEl = document.getElementById("fps");
const localVideo = document.getElementById("localVideo");
const remoteVideo = document.getElementById("remoteVideo");

let pc;
let localStream;
let controlChannel;
let fpsFrames = 0;
let fpsStartedAt = performance.now();
let statsTimer;

const targetVideoWidth = 960;
const targetVideoHeight = 540;
const defaultTargetFps = 60;
const targetFps = resolveTargetFps();
const targetVideoBitrate = targetFps > 30 ? 8_000_000 : 4_000_000;

startButton.addEventListener("click", start);
stopButton.addEventListener("click", stop);
characterSelect.addEventListener("change", sendSettings);
manyFacesToggle.addEventListener("change", sendSettings);

loadCharacters();
refreshHealth();
window.setInterval(refreshHealth, 3000);

function resolveTargetFps() {
    const params = new URLSearchParams(window.location.search);
    const rawValue = params.get("fps") || localStorage.getItem("dod.webrtcTargetFps");
    const parsedValue = Number.parseInt(rawValue || "", 10);
    if (Number.isFinite(parsedValue)) {
        return Math.max(15, Math.min(60, parsedValue));
    }
    return defaultTargetFps;
}

async function loadCharacters() {
    const response = await fetch("/api/characters");
    const characters = await response.json();
    characterSelect.replaceChildren();
    characters
        .filter((character) => character.id !== "default-human")
        .forEach((character) => {
            const option = document.createElement("option");
            option.value = character.id;
            option.textContent = character.name || character.id;
            characterSelect.append(option);
        });
}

async function start() {
    stop();
    setStatus("Запуск камеры");
    startButton.disabled = true;

    try {
        localStream = await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: {
                width: { ideal: targetVideoWidth },
                height: { ideal: targetVideoHeight },
                frameRate: { ideal: targetFps, max: targetFps }
            }
        });
        localVideo.srcObject = localStream;

        pc = new RTCPeerConnection({
            iceServers: []
        });
        controlChannel = pc.createDataChannel("control");
        controlChannel.onopen = sendSettings;
        controlChannel.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                if (message.type === "settings" && message.status !== "ok") {
                    setStatus(`Настройки не применены: ${message.status}`);
                }
            } catch (error) {
                setStatus("Ошибка control channel");
            }
        };

        pc.ontrack = (event) => {
            remoteVideo.srcObject = event.streams[0];
            setStatus("Live");
            startStats();
        };
        pc.onconnectionstatechange = () => {
            setStatus(pc.connectionState);
            if (["failed", "closed", "disconnected"].includes(pc.connectionState)) {
                stop();
            }
        };

        for (const track of localStream.getVideoTracks()) {
            track.contentHint = "detail";
            const sender = pc.addTrack(track, localStream);
            await configureSenderEncoding(sender);
        }

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitForIceGatheringComplete(pc);

        const response = await fetch("/offer", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                sdp: pc.localDescription.sdp,
                type: pc.localDescription.type,
                characterId: characterSelect.value,
                manyFaces: manyFacesToggle.checked
            })
        });
        if (!response.ok) {
            const body = await response.text();
            throw new Error(body);
        }

        const answer = await response.json();
        await pc.setRemoteDescription(answer);
        stopButton.disabled = false;
    } catch (error) {
        stop();
        setStatus(error.message || "Ошибка запуска");
    }
}

async function configureSenderEncoding(sender) {
    const parameters = sender.getParameters();
    parameters.encodings = parameters.encodings && parameters.encodings.length > 0
        ? parameters.encodings
        : [{}];
    parameters.encodings[0].maxBitrate = targetVideoBitrate;
    parameters.encodings[0].maxFramerate = targetFps;
    parameters.encodings[0].scaleResolutionDownBy = 1;
    try {
        await sender.setParameters(parameters);
    } catch (error) {
        console.warn("Unable to apply video encoding parameters", error);
    }
}

function stop() {
    if (statsTimer) {
        window.clearInterval(statsTimer);
        statsTimer = undefined;
    }
    if (pc) {
        pc.close();
        pc = undefined;
    }
    controlChannel = undefined;
    if (localStream) {
        localStream.getTracks().forEach((track) => track.stop());
        localStream = undefined;
    }
    localVideo.srcObject = null;
    remoteVideo.srcObject = null;
    fpsFrames = 0;
    fpsStartedAt = performance.now();
    fpsEl.textContent = "0";
    startButton.disabled = false;
    stopButton.disabled = true;
    setStatus("Ожидание");
}

function sendSettings() {
    if (!controlChannel || controlChannel.readyState !== "open") {
        return;
    }
    controlChannel.send(JSON.stringify({
        type: "settings",
        characterId: characterSelect.value,
        manyFaces: manyFacesToggle.checked
    }));
}

function waitForIceGatheringComplete(connection) {
    if (connection.iceGatheringState === "complete") {
        return Promise.resolve();
    }
    return new Promise((resolve) => {
        const checkState = () => {
            if (connection.iceGatheringState === "complete") {
                connection.removeEventListener("icegatheringstatechange", checkState);
                resolve();
            }
        };
        connection.addEventListener("icegatheringstatechange", checkState);
    });
}

function startStats() {
    if (statsTimer) {
        window.clearInterval(statsTimer);
    }
    fpsFrames = 0;
    fpsStartedAt = performance.now();
    const callback = () => {
        fpsFrames += 1;
        const now = performance.now();
        if (now - fpsStartedAt >= 1000) {
            fpsEl.textContent = String(Math.round((fpsFrames * 1000) / (now - fpsStartedAt)));
            fpsFrames = 0;
            fpsStartedAt = now;
        }
        if (remoteVideo.requestVideoFrameCallback) {
            remoteVideo.requestVideoFrameCallback(callback);
        }
    };
    if (remoteVideo.requestVideoFrameCallback) {
        remoteVideo.requestVideoFrameCallback(callback);
    } else {
        statsTimer = window.setInterval(() => {
            fpsEl.textContent = String(Math.round(remoteVideo.getVideoPlaybackQuality().totalVideoFrames || 0));
        }, 1000);
    }
}

async function refreshHealth() {
    try {
        const response = await fetch("/health");
        const health = await response.json();
        if (!localStream) {
            setStatus(health.ready ? "Готов" : "Модель не готова");
        }
    } catch (error) {
        if (!localStream) {
            setStatus("Сервер недоступен");
        }
    }
}

function setStatus(value) {
    statusEl.textContent = value;
}
