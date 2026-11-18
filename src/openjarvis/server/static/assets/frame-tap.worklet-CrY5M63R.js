/*
 * Procesador de audio del HUD. Corre en el hilo de audio del navegador y
 * agrupa las muestras del micrófono en bloques de tamaño fijo, para que el
 * detector de voz reciba siempre la misma duración por bloque.
 *
 * Es un archivo aparte (no código en línea cargado desde un blob:) porque la
 * política de seguridad del servidor solo permite scripts del mismo origen.
 */
class FrameTap extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.frame = new Float32Array(options.processorOptions.frameSize);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0][0];
    if (!channel) return true;

    let offset = 0;
    while (offset < channel.length) {
      const count = Math.min(channel.length - offset, this.frame.length - this.filled);
      this.frame.set(channel.subarray(offset, offset + count), this.filled);
      this.filled += count;
      offset += count;
      if (this.filled === this.frame.length) {
        // Se envía una copia: el búfer original se sigue reutilizando.
        this.port.postMessage(this.frame.slice(0));
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor('hud-frame-tap', FrameTap);
