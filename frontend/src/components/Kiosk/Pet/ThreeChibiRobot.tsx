import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import type { PetState } from './types';

export interface ThreeChibiRobotProps {
  state?: PetState | string;
  isDragging?: boolean;
  dragDeltaX?: number;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Draws dynamic LED visor expressions matching the reference image.
 */
function drawVisorTexture(
  ctx: CanvasRenderingContext2D,
  state: string,
  blinkProgress: number
): void {
  const w = 512;
  const h = 256;
  ctx.clearRect(0, 0, w, h);

  const isError = state === 'failed' || state === 'error';
  const primaryColor = isError ? '#ff3b30' : '#00f6ff';

  // Deep royal electric blue glass matching reference image
  const grad = ctx.createRadialGradient(w / 2, h / 2, 20, w / 2, h / 2, w * 0.48);
  if (isError) {
    grad.addColorStop(0, '#3a0808');
    grad.addColorStop(1, '#140202');
  } else {
    grad.addColorStop(0, '#0e4ba6');
    grad.addColorStop(0.55, '#06296b');
    grad.addColorStop(0.9, '#021338');
    grad.addColorStop(1, '#01091a');
  }
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);

  // LED Cyan glow
  ctx.strokeStyle = primaryColor;
  ctx.fillStyle = primaryColor;
  ctx.shadowColor = primaryColor;
  ctx.shadowBlur = 28;
  ctx.lineWidth = 22;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  if (blinkProgress > 0.8) {
    // Blinking flat line
    ctx.beginPath();
    ctx.moveTo(140, 135);
    ctx.lineTo(210, 135);
    ctx.moveTo(302, 135);
    ctx.lineTo(372, 135);
    ctx.stroke();
    return;
  }

  const s = state.toLowerCase();

  if (s === 'alert' || s === 'listening') {
    // Wide glowing curious eyes
    ctx.beginPath();
    ctx.arc(175, 130, 36, 0, Math.PI * 2);
    ctx.arc(337, 130, 36, 0, Math.PI * 2);
    ctx.fill();
  } else if (s === 'failed' || s === 'error') {
    // Cross / dizzy eyes > <
    ctx.beginPath();
    // Left X
    ctx.moveTo(150, 110);
    ctx.lineTo(200, 150);
    ctx.moveTo(200, 110);
    ctx.lineTo(150, 150);
    // Right X
    ctx.moveTo(312, 110);
    ctx.lineTo(362, 150);
    ctx.moveTo(362, 110);
    ctx.lineTo(312, 150);
    ctx.stroke();
  } else if (s === 'thinking' || s === 'busy' || s === 'processing') {
    // Radar / scanning dots
    const pulse = (Date.now() / 200) % 3;
    for (let i = 0; i < 3; i++) {
      ctx.beginPath();
      ctx.arc(206 + i * 50, 130, i === Math.floor(pulse) ? 18 : 10, 0, Math.PI * 2);
      ctx.fill();
    }
  } else if (s === 'speaking') {
    // Talking pulse arches + audio wave bar
    ctx.beginPath();
    ctx.arc(175, 125, 34, Math.PI * 1.15, Math.PI * 1.85);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(337, 125, 34, Math.PI * 1.15, Math.PI * 1.85);
    ctx.stroke();
    // Small mouth voice indicator
    ctx.lineWidth = 10;
    const mouthW = 20 + Math.sin(Date.now() / 100) * 16;
    ctx.beginPath();
    ctx.moveTo(256 - mouthW, 175);
    ctx.lineTo(256 + mouthW, 175);
    ctx.stroke();
  } else {
    // Standard happy smiling curved arches ^ ^ (Exact match to reference photo!)
    ctx.beginPath();
    ctx.arc(175, 140, 36, Math.PI * 1.15, Math.PI * 1.85);
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(337, 140, 36, Math.PI * 1.15, Math.PI * 1.85);
    ctx.stroke();
  }
}

/**
 * ThreeChibiRobot builds and renders the exact 3D Chibi AI Assistant Mascot
 * matching the user's reference design using Three.js WebGL primitives.
 */
export const ThreeChibiRobot: React.FC<ThreeChibiRobotProps> = ({
  state = 'idle',
  isDragging = false,
  dragDeltaX = 0,
  className = '',
  style,
}) => {
  const mountRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const isDraggingRef = useRef(isDragging);
  isDraggingRef.current = isDragging;
  const dragDeltaRef = useRef(dragDeltaX);
  dragDeltaRef.current = dragDeltaX;

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    const width = container.clientWidth || 180;
    const height = container.clientHeight || 180;

    // 1. Scene & Camera
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 100);
    camera.position.set(0, 0.2, 3.8);

    // 2. Renderer
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width, height);
      renderer.domElement.style.width = '100%';
      renderer.domElement.style.height = '100%';
      renderer.domElement.style.display = 'block';
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.1;
      container.appendChild(renderer.domElement);
    } catch {
      return;
    }

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const newW = entry.contentRect.width;
        const newH = entry.contentRect.height;
        if (newW > 0 && newH > 0) {
          camera.aspect = newW / newH;
          camera.updateProjectionMatrix();
          renderer.setSize(newW, newH);
        }
      }
    });
    resizeObserver.observe(container);

    // 3. Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 1.3);
    scene.add(ambientLight);

    const dirLightFront = new THREE.DirectionalLight(0xffffff, 1.5);
    dirLightFront.position.set(1.5, 3, 3);
    scene.add(dirLightFront);

    const dirLightFill = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLightFill.position.set(-2, 1.5, 2.5);
    scene.add(dirLightFill);

    const dirLightBack = new THREE.DirectionalLight(0x00f0ff, 1.1);
    dirLightBack.position.set(-2, 2, -2);
    scene.add(dirLightBack);

    // 4. Materials
    // Glossy White Plastic Shell
    const whiteShellMat = new THREE.MeshStandardMaterial({
      color: 0xfdfdfd,
      roughness: 0.22,
      metalness: 0.04,
    });

    // Vivid Cyan / Turquoise Accent Trim
    const cyanAccentMat = new THREE.MeshStandardMaterial({
      color: 0x00e5ff,
      roughness: 0.25,
      metalness: 0.1,
    });

    // Dark accents
    const darkAccentMat = new THREE.MeshStandardMaterial({
      color: 0x1a2233,
      roughness: 0.3,
      metalness: 0.2,
    });

    // Dynamic Visor Canvas & Texture
    const visorCanvas = document.createElement('canvas');
    visorCanvas.width = 512;
    visorCanvas.height = 256;
    const visorCtx = visorCanvas.getContext('2d');
    const visorTexture = new THREE.CanvasTexture(visorCanvas);
    visorTexture.colorSpace = THREE.SRGBColorSpace;

    const visorMat = new THREE.MeshStandardMaterial({
      map: visorTexture,
      emissiveMap: visorTexture,
      emissive: new THREE.Color(0xffffff),
      emissiveIntensity: 1.2,
      roughness: 0.1,
      metalness: 0.05,
    });

    // 5. Robot Hierarchy
    const robotRoot = new THREE.Group();
    scene.add(robotRoot);

    // --- HEAD GROUP ---
    const headGroup = new THREE.Group();
    headGroup.position.set(0, 0.45, 0);
    robotRoot.add(headGroup);

    // Head Base (Rounded Glossy White Helmet)
    const headGeo = new THREE.SphereGeometry(0.68, 64, 48);
    headGeo.scale(1.0, 0.94, 0.88);
    const headMesh = new THREE.Mesh(headGeo, whiteShellMat);
    headGroup.add(headMesh);

    // Integrated Curved Visor Screen (Embedded closed ellipsoid with planar UV mapping)
    const visorGeo = new THREE.SphereGeometry(0.64, 64, 48);
    visorGeo.scale(0.96, 0.74, 0.76);
    const vPos = visorGeo.attributes.position;
    const vUv = visorGeo.attributes.uv;
    for (let i = 0; i < vPos.count; i++) {
      const x = vPos.getX(i);
      const y = vPos.getY(i);
      vUv.setXY(i, (x / 1.1) + 0.5, (y / 0.85) + 0.5);
    }
    vUv.needsUpdate = true;

    const visorMesh = new THREE.Mesh(visorGeo, visorMat);
    visorMesh.position.set(0, 0.04, 0.18);
    headGroup.add(visorMesh);

    // Cyan Ear Covers & Antenna Fins (Smooth rounded geometries, no sharp edges)
    const earPadGeo = new THREE.SphereGeometry(0.25, 32, 24);
    earPadGeo.scale(0.48, 1.0, 1.0);

    const earPortGeo = new THREE.SphereGeometry(0.13, 24, 16);
    earPortGeo.scale(0.52, 1.0, 1.0);

    const antennaFinGeo = new THREE.CapsuleGeometry(0.065, 0.20, 16, 24);
    antennaFinGeo.scale(0.65, 1.0, 1.3);

    // Right Ear
    const rightEarGroup = new THREE.Group();
    rightEarGroup.position.set(0.66, 0.05, 0);
    headGroup.add(rightEarGroup);

    const rightEarPad = new THREE.Mesh(earPadGeo, whiteShellMat);
    rightEarGroup.add(rightEarPad);
    const rightEarPort = new THREE.Mesh(earPortGeo, darkAccentMat);
    rightEarGroup.add(rightEarPort);
    const rightAntenna = new THREE.Mesh(antennaFinGeo, cyanAccentMat);
    rightAntenna.position.set(0.02, 0.24, 0);
    rightEarGroup.add(rightAntenna);

    // Left Ear
    const leftEarGroup = new THREE.Group();
    leftEarGroup.position.set(-0.66, 0.05, 0);
    headGroup.add(leftEarGroup);

    const leftEarPad = new THREE.Mesh(earPadGeo, whiteShellMat);
    leftEarGroup.add(leftEarPad);
    const leftEarPort = new THREE.Mesh(earPortGeo, darkAccentMat);
    leftEarGroup.add(leftEarPort);
    const leftAntenna = new THREE.Mesh(antennaFinGeo, cyanAccentMat);
    leftAntenna.position.set(-0.02, 0.24, 0);
    leftEarGroup.add(leftAntenna);

    // Top Crest / Fin (Soft rounded capsule ridge)
    const crestGeo = new THREE.CapsuleGeometry(0.08, 0.18, 16, 24);
    crestGeo.rotateX(Math.PI / 2);
    crestGeo.scale(0.85, 1.0, 1.0);
    const crestMesh = new THREE.Mesh(crestGeo, whiteShellMat);
    crestMesh.position.set(0, 0.63, -0.05);
    headGroup.add(crestMesh);

    // --- BODY GROUP (Floating Pod Torso - NO LEGS) ---
    const bodyGroup = new THREE.Group();
    bodyGroup.position.set(0, -0.26, 0);
    robotRoot.add(bodyGroup);

    // Floating egg/pod torso
    const torsoGeo = new THREE.SphereGeometry(0.5, 32, 32);
    torsoGeo.scale(0.85, 1.05, 0.82);
    const torsoMesh = new THREE.Mesh(torsoGeo, whiteShellMat);
    bodyGroup.add(torsoMesh);

    // Neck joint ring
    const neckRingGeo = new THREE.TorusGeometry(0.25, 0.04, 16, 32);
    neckRingGeo.rotateX(Math.PI / 2);
    const neckRingMesh = new THREE.Mesh(neckRingGeo, darkAccentMat);
    neckRingMesh.position.set(0, 0.44, 0);
    bodyGroup.add(neckRingMesh);

    // Cyan Chest Shield Badge
    const badgeShape = new THREE.Shape();
    badgeShape.moveTo(-0.16, 0.12);
    badgeShape.lineTo(0.16, 0.12);
    badgeShape.lineTo(0.12, -0.06);
    badgeShape.lineTo(0, -0.16);
    badgeShape.lineTo(-0.12, -0.06);
    badgeShape.closePath();

    const badgeGeo = new THREE.ShapeGeometry(badgeShape);
    badgeGeo.scale(1.1, 1.1, 1.1);
    const badgeMat = cyanAccentMat.clone();
    badgeMat.side = THREE.DoubleSide;
    const badgeMesh = new THREE.Mesh(badgeGeo, badgeMat);
    badgeMesh.position.set(0, 0.08, 0.43);
    bodyGroup.add(badgeMesh);

    // --- ARMS ---
    const armGeo = new THREE.CapsuleGeometry(0.1, 0.32, 12, 16);

    // Left Arm (Waving Arm)
    const leftArmGroup = new THREE.Group();
    leftArmGroup.position.set(0.48, 0.1, 0.05);
    bodyGroup.add(leftArmGroup);

    const leftArmMesh = new THREE.Mesh(armGeo, whiteShellMat);
    leftArmMesh.position.set(0.16, 0.12, 0.1);
    leftArmMesh.rotation.z = -Math.PI / 3.8;
    leftArmGroup.add(leftArmMesh);

    // Right Arm (Resting Arm)
    const rightArmGroup = new THREE.Group();
    rightArmGroup.position.set(-0.48, 0.05, 0);
    bodyGroup.add(rightArmGroup);

    const rightArmMesh = new THREE.Mesh(armGeo, whiteShellMat);
    rightArmMesh.position.set(-0.06, -0.12, 0);
    rightArmMesh.rotation.z = Math.PI / 7;
    rightArmGroup.add(rightArmMesh);

    // 6. Interaction & Mouse Tracking (Only tracks when cursor enters robot proximity zone)
    const PROXIMITY_ZONE_RADIUS = 280; // Cursor must be within 280px to turn head
    const mouseTarget = { x: 0, y: 0 };

    const onPointerMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const petCenterX = rect.left + rect.width / 2;
      const petCenterY = rect.top + rect.height / 2;
      const dist = Math.hypot(e.clientX - petCenterX, e.clientY - petCenterY);

      if (dist >= PROXIMITY_ZONE_RADIUS) {
        // Outside the zone: smoothly look straight forward
        mouseTarget.x = 0;
        mouseTarget.y = 0;
        return;
      }

      // Smooth falloff factor: 1 near mascot center, 0 at outer boundary
      const factor = Math.cos((dist / PROXIMITY_ZONE_RADIUS) * (Math.PI / 2));
      const dx = (e.clientX - petCenterX) / PROXIMITY_ZONE_RADIUS;
      const dy = (e.clientY - petCenterY) / PROXIMITY_ZONE_RADIUS;
      mouseTarget.x = THREE.MathUtils.clamp(dx * 0.45 * factor, -0.35, 0.35);
      mouseTarget.y = THREE.MathUtils.clamp(-dy * 0.45 * factor, -0.28, 0.28);
    };

    const onPointerLeave = () => {
      mouseTarget.x = 0;
      mouseTarget.y = 0;
    };

    window.addEventListener('mousemove', onPointerMove);
    window.addEventListener('mouseleave', onPointerLeave);

    // 7. Animation Loop
    let animationFrameId: number;
    let clock = 0;
    let lastBlinkTime = 0;

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      clock += 0.035;

      // Floating bobbing motion
      const floatY = Math.sin(clock * 1.8) * 0.06;
      robotRoot.position.y = floatY;

      // Smooth Head Tracking to Mouse
      headGroup.rotation.y = THREE.MathUtils.lerp(headGroup.rotation.y, mouseTarget.x, 0.08);
      headGroup.rotation.x = THREE.MathUtils.lerp(headGroup.rotation.x, -mouseTarget.y, 0.08);
      bodyGroup.rotation.y = THREE.MathUtils.lerp(bodyGroup.rotation.y, mouseTarget.x * 0.4, 0.08);

      // Drag Tilt
      if (isDraggingRef.current) {
        const tilt = THREE.MathUtils.clamp(dragDeltaRef.current * 0.04, -0.3, 0.3);
        robotRoot.rotation.z = THREE.MathUtils.lerp(robotRoot.rotation.z, tilt, 0.15);
      } else {
        robotRoot.rotation.z = THREE.MathUtils.lerp(robotRoot.rotation.z, 0, 0.1);
      }

      // Waving hand oscillation
      const isReviewOrWaving =
        stateRef.current === 'waving' ||
        stateRef.current === 'review' ||
        stateRef.current === 'completed';
      const waveSpeed = isReviewOrWaving ? 8 : 4;
      leftArmGroup.rotation.z = Math.sin(clock * waveSpeed) * 0.25;
      leftArmGroup.rotation.y = Math.cos(clock * waveSpeed) * 0.15;

      // Periodic Blinking (every ~4.5 seconds)
      const now = clock;
      if (now - lastBlinkTime > 4.5) {
        lastBlinkTime = now;
      }
      const blinkDelta = now - lastBlinkTime;
      const blinkProgress = blinkDelta < 0.25 ? Math.sin((blinkDelta / 0.25) * Math.PI) : 0;

      // Update LED Visor Texture
      if (visorCtx) {
        drawVisorTexture(visorCtx, stateRef.current, blinkProgress);
        visorTexture.needsUpdate = true;
      }

      renderer.render(scene, camera);
    };

    animate();

    // 8. Cleanup
    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('mousemove', onPointerMove);
      window.removeEventListener('mouseleave', onPointerLeave);
      cancelAnimationFrame(animationFrameId);
      renderer.dispose();
      visorTexture.dispose();
      headGeo.dispose();
      visorGeo.dispose();
      earPadGeo.dispose();
      earPortGeo.dispose();
      antennaFinGeo.dispose();
      crestGeo.dispose();
      torsoGeo.dispose();
      neckRingGeo.dispose();
      badgeGeo.dispose();
      armGeo.dispose();
      whiteShellMat.dispose();
      cyanAccentMat.dispose();
      darkAccentMat.dispose();
      visorMat.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      ref={mountRef}
      data-testid="three-chibi-robot"
      className={`w-full h-full pointer-events-auto cursor-grab active:cursor-grabbing ${className}`}
      style={style}
    />
  );
};
