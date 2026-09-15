import { useEffect, useRef, useState } from 'react';
import { useDraggableResizable } from '@/hooks/useDraggableResizable';
import { Maximize2, Minimize2 } from 'lucide-react';

export function ScreenShareView({
  stream,
  floating = false,
  initialPlacement = 'center',
}: {
  stream: MediaStream | null;
  floating?: boolean;
  initialPlacement?: 'top-right' | 'center';
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [aspectRatio, setAspectRatio] = useState<number>(16 / 9);

  const {
    position,
    size,
    isDragging,
    isResizing,
    isMaximized,
    toggleMaximize,
    cardHandlers,
    getResizeHandleProps,
  } = useDraggableResizable({
    initialPlacement,
    aspectRatio,
    minWidth: 160,
  });

  // srcObject is a property, never an attribute — it cannot be set in JSX.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = stream;

    const tryPlay = () => {
      if (video && video.paused) {
        video.play().catch(() => {});
      }
    };

    if (stream) {
      tryPlay();
      const [track] = stream.getVideoTracks();
      if (track) {
        track.onunmute = tryPlay;
      }
    }

    const handleLoadedMetadata = () => {
      tryPlay();
      if (video.videoWidth > 0 && video.videoHeight > 0) {
        setAspectRatio(video.videoWidth / video.videoHeight);
      }
    };

    const handleCanPlay = () => {
      tryPlay();
    };

    video.addEventListener('loadedmetadata', handleLoadedMetadata);
    video.addEventListener('canplay', handleCanPlay);
    return () => {
      video.removeEventListener('loadedmetadata', handleLoadedMetadata);
      video.removeEventListener('canplay', handleCanPlay);
    };
  }, [stream]);

  if (!floating) {
    return (
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        className="absolute inset-0 h-full w-full"
        style={{ objectFit: 'contain', background: '#06060f' }}
      />
    );
  }

  return (
    <div
      {...cardHandlers}
      onDoubleClick={(e) => {
        e.stopPropagation();
        toggleMaximize();
      }}
      data-testid="screen-share-view"
      data-maximized={isMaximized ? 'true' : 'false'}
      className={`fixed z-25 select-none overflow-hidden touch-none transition-[box-shadow,border-color] group ${
        isMaximized
          ? 'rounded-none border-0 shadow-none'
          : 'rounded-2xl border'
      } ${
        isDragging
          ? 'shadow-[0_24px_60px_rgba(0,0,0,0.85)] ring-1 ring-white/20 border-white/30'
          : isResizing
            ? 'shadow-[0_20px_50px_rgba(0,0,0,0.8)] border-white/25'
            : 'shadow-[0_12px_36px_rgba(0,0,0,0.65)] hover:border-white/25'
      }`}
      style={{
        left: `${position.x}px`,
        top: `${position.y}px`,
        width: `${size.width}px`,
        height: `${size.height}px`,
        background: '#06060f',
        borderColor: isMaximized ? 'transparent' : 'rgba(255, 255, 255, 0.16)',
      }}
    >
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        className="w-full h-full object-contain pointer-events-none"
      />

      {/* Sleek Minimal Hover Controls (Top-Right) */}
      <div
        className="absolute top-2.5 right-2.5 z-30 flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity duration-200"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            toggleMaximize();
          }}
          title={isMaximized ? 'Restore size (Thu nhỏ lại)' : 'Maximize (Phóng to hết cỡ)'}
          className="w-7 h-7 rounded-lg bg-black/60 hover:bg-black/85 backdrop-blur border border-white/15 flex items-center justify-center text-slate-300 hover:text-white transition-all cursor-pointer shadow-lg"
        >
          {isMaximized ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
        </button>
      </div>

      {/* 4 Edge Resize Handles (Transparent hit areas, no colored background) */}
      {/* Top Edge (N) */}
      <div
        {...getResizeHandleProps('n')}
        title="Resize Top"
        className="absolute top-0 inset-x-4 h-3 cursor-ns-resize touch-none z-20"
      />

      {/* Bottom Edge (S) */}
      <div
        {...getResizeHandleProps('s')}
        title="Resize Bottom"
        className="absolute bottom-0 inset-x-4 h-3 cursor-ns-resize touch-none z-20"
      />

      {/* Left Edge (W) */}
      <div
        {...getResizeHandleProps('w')}
        title="Resize Left"
        className="absolute left-0 inset-y-4 w-3 cursor-ew-resize touch-none z-20"
      />

      {/* Right Edge (E) */}
      <div
        {...getResizeHandleProps('e')}
        title="Resize Right"
        className="absolute right-0 inset-y-4 w-3 cursor-ew-resize touch-none z-20"
      />

      {/* 4 Corner Resize Handles */}
      {/* NW (Top-Left) */}
      <div
        {...getResizeHandleProps('nw')}
        title="Resize Top-Left"
        className="group/nw absolute -top-1 -left-1 w-8 h-8 cursor-nwse-resize touch-none z-30 flex items-start justify-start p-1.5"
      >
        <div className="w-2.5 h-2.5 border-t-2 border-l-2 border-cyan-400/40 rounded-tl-[3px] group-hover/nw:border-cyan-300 group-hover/nw:scale-125 transition-all" />
      </div>

      {/* NE (Top-Right) */}
      <div
        {...getResizeHandleProps('ne')}
        title="Resize Top-Right"
        className="group/ne absolute -top-1 -right-1 w-8 h-8 cursor-nesw-resize touch-none z-30 flex items-start justify-end p-1.5"
      >
        <div className="w-2.5 h-2.5 border-t-2 border-r-2 border-cyan-400/40 rounded-tr-[3px] group-hover/ne:border-cyan-300 group-hover/ne:scale-125 transition-all" />
      </div>

      {/* SW (Bottom-Left) */}
      <div
        {...getResizeHandleProps('sw')}
        title="Resize Bottom-Left"
        className="group/sw absolute -bottom-1 -left-1 w-8 h-8 cursor-nesw-resize touch-none z-30 flex items-end justify-start p-1.5"
      >
        <div className="w-2.5 h-2.5 border-b-2 border-l-2 border-cyan-400/40 rounded-bl-[3px] group-hover/sw:border-cyan-300 group-hover/sw:scale-125 transition-all" />
      </div>

      {/* SE (Bottom-Right) */}
      <div
        {...getResizeHandleProps('se')}
        title="Resize Bottom-Right"
        className="group/se absolute -bottom-1 -right-1 w-8 h-8 cursor-nwse-resize touch-none z-30 flex items-end justify-end p-1.5"
      >
        <div className="w-2.5 h-2.5 border-b-2 border-r-2 border-cyan-400/40 rounded-br-[3px] group-hover/se:border-cyan-300 group-hover/se:scale-125 transition-all" />
      </div>
    </div>
  );
}
