# DeepFaceLive Experiment

This folder is a launcher project for testing DeepFaceLive next to the current Deep-Live-Cam prototype.

DeepFaceLive is archived upstream, and the official Windows quick start recommends the portable Windows build instead of installing source dependencies manually.

## Setup

1. Open the official repository:

   ```text
   https://github.com/iperov/DeepFaceLive
   ```

2. Download one of the official Windows 10 x64 builds from the Releases section.

   Use the NVIDIA build for an NVIDIA GPU. Use the DirectX12 build if you need a broader Windows GPU path.

3. Unpack the build into:

   ```text
   experiments\DeepFaceLive\portable
   ```

   It is also fine to unpack it elsewhere and pass that path to the launcher.

## Run

From the repository root:

```powershell
.\experiments\DeepFaceLive\run-deepfacelive.ps1
```

Or with an explicit portable path:

```powershell
.\experiments\DeepFaceLive\run-deepfacelive.ps1 -PortableDir "D:\DeepFaceLive"
```

## Compare With Browser Prototype

Browser/WebRTC version:

```powershell
.\run-webrtc.ps1
```

Open:

```text
http://127.0.0.1:8088
```

Use the physical camera in only one app at a time unless the camera driver supports multiple consumers. For a side-by-side demo, leave both apps open and start/stop the camera in one before enabling it in the other.

## Notes

- DeepFaceLive has two main modes: trained DFM face models and Insight/single-photo face swap.
- The upstream README says higher quality depends heavily on face matching, module tuning, and GPU performance.
- For video calls, DeepFaceLive outputs a window; OBS Virtual Camera can capture that output window.
