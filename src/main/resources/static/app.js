const sourceVideo = document.getElementById("sourceVideo");
const processedCanvas = document.getElementById("processedCanvas");
const captureCanvas = document.getElementById("captureCanvas");
const cameraButton = document.getElementById("cameraButton");
const cameraStatus = document.getElementById("cameraStatus");
const workerStatus = document.getElementById("workerStatus");
const fpsMetric = document.getElementById("fpsMetric");
const latencyMetric = document.getElementById("latencyMetric");
const inferenceMetric = document.getElementById("inferenceMetric");
const charactersContainer = document.getElementById("charactersContainer");
const manyFacesToggle = document.getElementById("manyFacesToggle");
const processingProfileButtons = Array.from(document.querySelectorAll("[data-processing-profile]"));
const message = document.getElementById("message");

const captureContext = captureCanvas.getContext("2d", { willReadFrequently: true });
const processedContext = processedCanvas.getContext("2d");
const preferredCharacterId = localStorage.getItem("dod.characterId");
const preferredManyFaces = localStorage.getItem("dod.manyFaces") === "true";
const preferredProcessingProfileId = localStorage.getItem("dod.processingProfile");
const defaultTargetFps = 60;
const targetFps = resolveTargetFps();
const frameIntervalMs = 1000 / targetFps;
const cameraProfiles = [
    { width: 1920, height: 1080 },
    { width: 1280, height: 720 }
];
const processingProfiles = {
    "720p": { width: 1280, height: 720, jpegQuality: 0.84 }
};
const defaultProcessingProfileId = "720p";
const socketReconnectDelayMs = 1000;
const hiddenCharacterIds = new Set(["default-human"]);
const metricWindowSize = 30;
const maxInFlightFrames = 2;

let mediaStream;
let socket;
let selectedCharacterId = preferredCharacterId || "";
let selectedProcessingProfileId = processingProfiles[preferredProcessingProfileId]
    ? preferredProcessingProfileId
    : defaultProcessingProfileId;
let inFlightFrames = 0;
let sequence = 0;
let minimumAcceptedSequence = 0;
let latestRenderedSequence = -1;
let framesReceived = 0;
let fpsWindowStarted = performance.now();
let lastFrameSentAt = 0;
let latencyWindow = [];
let inferenceWindow = [];
let sendLoopId;
let statusPollId;
let reconnectTimerId;

cameraButton.addEventListener("click", toggleCamera);
manyFacesToggle.checked = preferredManyFaces;
manyFacesToggle.addEventListener("change", () => {
    localStorage.setItem("dod.manyFaces", String(manyFacesToggle.checked));
});
processingProfileButtons.forEach((button) => {
    button.addEventListener("click", () => setProcessingProfile(button.dataset.processingProfile, true));
});
window.addEventListener("pagehide", stopCamera);
window.addEventListener("beforeunload", stopCamera);
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
        stopCamera();
    }
});

initialize();

function resolveTargetFps() {
    const params = new URLSearchParams(window.location.search);
    const rawValue = params.get("fps") || localStorage.getItem("dod.targetFps");
    const parsedValue = Number.parseInt(rawValue || "", 10);
    if (Number.isFinite(parsedValue)) {
        return Math.max(15, Math.min(60, parsedValue));
    }
    return defaultTargetFps;
}

async function initialize() {
    setProcessingProfile(selectedProcessingProfileId, false);
    await loadCharacters();
    await refreshStatus();
    statusPollId = window.setInterval(refreshStatus, 3000);
}

async function loadCharacters() {
    try {
        const response = await fetch("/api/characters");
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const characters = (await response.json()).filter((character) => !hiddenCharacterIds.has(character.id));
        renderCharacters(characters);
        const firstCharacter = characters[0]?.id || "";
        if (!selectedCharacterId || !characters.some((item) => item.id === selectedCharacterId)) {
            selectedCharacterId = firstCharacter;
        }
        if (selectedCharacterId) {
            await selectCharacter(selectedCharacterId, false);
        }
    } catch (error) {
        showMessage("Не удалось загрузить список лиц.");
    }
}

function renderCharacters(characters) {
    charactersContainer.replaceChildren();
    characters.forEach((character) => {
        const button = document.createElement("button");
        button.className = "character-card";
        button.type = "button";
        button.dataset.characterId = character.id;
        button.addEventListener("click", () => selectCharacter(character.id, true));

        const image = document.createElement("img");
        image.src = character.imageUrl;
        image.alt = "";

        const name = document.createElement("span");
        name.textContent = character.name;

        button.append(image, name);
        charactersContainer.append(button);
    });
    markSelectedCharacter();
}

async function selectCharacter(characterId, prepareRemote) {
    if (!characterId) {
        return;
    }
    hideMessage();
    selectedCharacterId = characterId;
    localStorage.setItem("dod.characterId", selectedCharacterId);
    markSelectedCharacter();

    if (!prepareRemote) {
        return;
    }
    try {
        const response = await fetch(`/api/characters/${encodeURIComponent(characterId)}/select`, {
            method: "POST"
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        if (!mediaStream) {
            await startCamera();
        }
    } catch (error) {
        showMessage("Это лицо пока не готово в движке.");
    }
}

function markSelectedCharacter() {
    document.querySelectorAll(".character-card").forEach((button) => {
        button.classList.toggle("selected", button.dataset.characterId === selectedCharacterId);
    });
}

function setProcessingProfile(profileId, persist) {
    if (!processingProfiles[profileId]) {
        return;
    }
    selectedProcessingProfileId = profileId;
    if (persist) {
        localStorage.setItem("dod.processingProfile", selectedProcessingProfileId);
        minimumAcceptedSequence = sequence;
        clearProcessedFrame();
        resizeCaptureCanvasForProcessing();
    }
    processingProfileButtons.forEach((button) => {
        const selected = button.dataset.processingProfile === selectedProcessingProfileId;
        button.classList.toggle("selected", selected);
        button.setAttribute("aria-pressed", String(selected));
    });
}

function toggleCamera() {
    if (mediaStream) {
        stopCamera();
        return;
    }
    startCamera();
}

async function startCamera() {
    hideMessage();
    if (!selectedCharacterId) {
        showMessage("Сначала выберите лицо.");
        return;
    }

    setCameraState("starting");
    cameraButton.textContent = "Остановить";

    try {
        mediaStream = await openCameraStream();
        sourceVideo.srcObject = mediaStream;
        await sourceVideo.play();
        resizeCaptureCanvasForProcessing();
        openSocket();
        setCameraState("active");
        sendLoopId = window.requestAnimationFrame(sendLoop);
    } catch (error) {
        setCameraState("error");
        cameraButton.textContent = "Запустить";
        mediaStream = undefined;
        showMessage("Камера недоступна. Проверьте разрешение браузера.");
    }
}

function stopCamera() {
    if (sendLoopId) {
        window.cancelAnimationFrame(sendLoopId);
        sendLoopId = undefined;
    }
    clearReconnectTimer();
    if (socket) {
        socket.close();
        socket = undefined;
    }
    if (mediaStream) {
        mediaStream.getTracks().forEach((track) => track.stop());
        mediaStream = undefined;
    }
    sourceVideo.pause();
    sourceVideo.srcObject = null;
    clearProcessedFrame();
    inFlightFrames = 0;
    latestRenderedSequence = -1;
    framesReceived = 0;
    fpsWindowStarted = performance.now();
    latencyWindow = [];
    inferenceWindow = [];
    fpsMetric.textContent = "0";
    latencyMetric.textContent = "0";
    inferenceMetric.textContent = "0";
    cameraButton.textContent = "Запустить";
    setCameraState("idle");
}

async function openCameraStream() {
    let lastError;
    for (const profile of cameraProfiles) {
        try {
            return await navigator.mediaDevices.getUserMedia({
                audio: false,
                video: {
                    width: { exact: profile.width },
                    height: { exact: profile.height },
                    frameRate: { ideal: targetFps, max: targetFps }
                }
            });
        } catch (error) {
            lastError = error;
        }
    }
    throw lastError;
}

function openSocket() {
    clearReconnectTimer();
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const currentSocket = new WebSocket(`${protocol}://${window.location.host}/ws/video`);
    socket = currentSocket;
    currentSocket.binaryType = "arraybuffer";
    currentSocket.onopen = () => setWorkerState("connected");
    currentSocket.onclose = () => {
        if (socket === currentSocket) {
            socket = undefined;
            handleSocketUnavailable("offline");
            scheduleSocketReconnect();
        }
    };
    currentSocket.onerror = () => {
        if (socket === currentSocket) {
            handleSocketUnavailable("error");
        }
        currentSocket.close();
    };
    currentSocket.onmessage = handleProcessedFrame;
}

function handleSocketUnavailable(state) {
    setWorkerState(state);
    inFlightFrames = 0;
    clearProcessedFrame();
}

function scheduleSocketReconnect() {
    if (!mediaStream || reconnectTimerId) {
        return;
    }
    reconnectTimerId = window.setTimeout(() => {
        reconnectTimerId = undefined;
        if (mediaStream) {
            openSocket();
        }
    }, socketReconnectDelayMs);
}

function clearReconnectTimer() {
    if (reconnectTimerId) {
        window.clearTimeout(reconnectTimerId);
        reconnectTimerId = undefined;
    }
}

function sendLoop(now) {
    sendLoopId = window.requestAnimationFrame(sendLoop);
    if (!mediaStream || !socket || socket.readyState !== WebSocket.OPEN || inFlightFrames >= maxInFlightFrames) {
        return;
    }
    if (now - lastFrameSentAt < frameIntervalMs || sourceVideo.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
        return;
    }
    lastFrameSentAt = now;
    sendFrame();
}

function sendFrame() {
    inFlightFrames += 1;
    resizeCaptureCanvasForProcessing();
    captureContext.drawImage(sourceVideo, 0, 0, captureCanvas.width, captureCanvas.height);
    captureCanvas.toBlob(async (blob) => {
        if (!blob || !socket || socket.readyState !== WebSocket.OPEN) {
            inFlightFrames = Math.max(0, inFlightFrames - 1);
            return;
        }
        try {
            const imageBytes = await blob.arrayBuffer();
            const metadata = {
                characterId: selectedCharacterId,
                manyFaces: manyFacesToggle.checked,
                sequence: sequence++,
                capturedAtEpochMs: Date.now()
            };
            socket.send(packFrame(metadata, imageBytes));
        } catch (error) {
            inFlightFrames = Math.max(0, inFlightFrames - 1);
        }
    }, "image/jpeg", getSelectedProcessingProfile().jpegQuality);
}

function packFrame(metadata, imageBytes) {
    const headerBytes = new TextEncoder().encode(JSON.stringify(metadata));
    const payload = new Uint8Array(4 + headerBytes.length + imageBytes.byteLength);
    const view = new DataView(payload.buffer);
    view.setUint32(0, headerBytes.length, false);
    payload.set(headerBytes, 4);
    payload.set(new Uint8Array(imageBytes), 4 + headerBytes.length);
    return payload.buffer;
}

async function handleProcessedFrame(event) {
    inFlightFrames = Math.max(0, inFlightFrames - 1);
    const frame = unpackFrame(event.data);
    if (!frame) {
        return;
    }
    if (Number.isFinite(frame.metadata.sequence) && frame.metadata.sequence < minimumAcceptedSequence) {
        return;
    }
    if (Number.isFinite(frame.metadata.sequence) && frame.metadata.sequence <= latestRenderedSequence) {
        return;
    }
    updateFrameStatus(frame.metadata);
    try {
        const bitmap = await createImageBitmap(new Blob([frame.imageBytes], { type: "image/jpeg" }));
        resizeProcessedCanvas(bitmap.width, bitmap.height);
        processedContext.drawImage(bitmap, 0, 0, processedCanvas.width, processedCanvas.height);
        if (Number.isFinite(frame.metadata.sequence)) {
            latestRenderedSequence = frame.metadata.sequence;
        }
        bitmap.close();
    } catch (error) {
        showMessage("Движок вернул поврежденный кадр.");
    }
}

function unpackFrame(buffer) {
    if (buffer.byteLength < 4) {
        return null;
    }
    const view = new DataView(buffer);
    const headerLength = view.getUint32(0, false);
    if (headerLength <= 0 || buffer.byteLength < 4 + headerLength) {
        return null;
    }
    const headerBytes = buffer.slice(4, 4 + headerLength);
    const imageBytes = buffer.slice(4 + headerLength);
    return {
        metadata: JSON.parse(new TextDecoder().decode(headerBytes)),
        imageBytes
    };
}

function updateFrameStatus(metadata) {
    framesReceived += 1;
    const now = performance.now();
    if (now - fpsWindowStarted >= 1000) {
        fpsMetric.textContent = String(framesReceived);
        framesReceived = 0;
        fpsWindowStarted = now;
    }
    if (Number.isFinite(metadata.capturedAtEpochMs) && metadata.capturedAtEpochMs > 0) {
        pushMetric(latencyWindow, Math.max(0, Date.now() - metadata.capturedAtEpochMs));
        latencyMetric.textContent = String(Math.round(averageMetric(latencyWindow)));
    }
    if (Number.isFinite(metadata.inferenceMs)) {
        pushMetric(inferenceWindow, Math.max(0, metadata.inferenceMs));
        inferenceMetric.textContent = String(Math.round(averageMetric(inferenceWindow)));
    }
    setWorkerState(metadata.status === "ok" ? "ready" : metadata.status);
}

function pushMetric(windowValues, value) {
    windowValues.push(value);
    if (windowValues.length > metricWindowSize) {
        windowValues.shift();
    }
}

function averageMetric(windowValues) {
    if (windowValues.length === 0) {
        return 0;
    }
    return windowValues.reduce((sum, value) => sum + value, 0) / windowValues.length;
}

function resizeCaptureCanvasForProcessing() {
    const size = getProcessingFrameSize();
    if (captureCanvas.width !== size.width || captureCanvas.height !== size.height) {
        captureCanvas.width = size.width;
        captureCanvas.height = size.height;
    }
}

function getProcessingFrameSize() {
    const profile = getSelectedProcessingProfile();
    const sourceWidth = sourceVideo.videoWidth || profile.width;
    const sourceHeight = sourceVideo.videoHeight || profile.height;
    const scale = Math.min(1, profile.width / sourceWidth, profile.height / sourceHeight);
    return {
        width: Math.max(1, Math.round(sourceWidth * scale)),
        height: Math.max(1, Math.round(sourceHeight * scale))
    };
}

function getSelectedProcessingProfile() {
    return processingProfiles[selectedProcessingProfileId] || processingProfiles[defaultProcessingProfileId];
}

function resizeProcessedCanvas(width, height) {
    if (processedCanvas.width !== width || processedCanvas.height !== height) {
        processedCanvas.width = width;
        processedCanvas.height = height;
    }
}

function clearProcessedFrame() {
    processedContext.clearRect(0, 0, processedCanvas.width, processedCanvas.height);
}

async function refreshStatus() {
    try {
        const response = await fetch("/api/status");
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const status = await response.json();
        setWorkerState(status.workerReady ? "ready" : "not-ready");
    } catch (error) {
        setWorkerState("offline");
    }
}

function setCameraState(state) {
    cameraStatus.className = "status-pill";
    if (state === "active") {
        cameraStatus.textContent = "Камера включена";
        cameraStatus.classList.add("good");
        return;
    }
    if (state === "starting") {
        cameraStatus.textContent = "Камера запускается";
        cameraStatus.classList.add("warn");
        return;
    }
    if (state === "error") {
        cameraStatus.textContent = "Ошибка камеры";
        cameraStatus.classList.add("bad");
        return;
    }
    cameraStatus.textContent = "Камера выключена";
    cameraStatus.classList.add("muted");
}

function setWorkerState(state) {
    workerStatus.className = "status-pill";
    if (state === "no_face") {
        workerStatus.textContent = "Лицо не найдено";
        workerStatus.classList.add("warn");
        return;
    }
    if (state === "invalid_character") {
        workerStatus.textContent = "Лицо не готово";
        workerStatus.classList.add("warn");
        return;
    }
    if (state === "ready" || state === "connected") {
        workerStatus.textContent = "Движок готов";
        workerStatus.classList.add("good");
        return;
    }
    if (state === "not-ready") {
        workerStatus.textContent = "Движок загружается";
        workerStatus.classList.add("warn");
        return;
    }
    if (state === "error") {
        workerStatus.textContent = "Ошибка движка";
        workerStatus.classList.add("bad");
        return;
    }
    if (state === "processing_error") {
        workerStatus.textContent = "Ошибка обработки";
        workerStatus.classList.add("bad");
        return;
    }
    if (state === "model_not_ready") {
        workerStatus.textContent = "Движок загружается";
        workerStatus.classList.add("warn");
        return;
    }
    workerStatus.textContent = "Движок недоступен";
    workerStatus.classList.add("bad");
}

function showMessage(text) {
    message.textContent = text;
    message.classList.remove("hidden");
}

function hideMessage() {
    message.classList.add("hidden");
}
