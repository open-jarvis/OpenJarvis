import onnxWasmModuleUrl from 'onnxruntime-web/ort-wasm-simd-threaded.mjs?url';
import onnxWasmBinaryUrl from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url';
import { describe, expect, it } from 'vitest';

describe('Voice VAD assets', () => {
  it('resolves Vite-managed ONNX Runtime loader and binary URLs', () => {
    expect(onnxWasmModuleUrl).toContain('ort-wasm-simd-threaded.mjs');
    expect(onnxWasmBinaryUrl).toContain('ort-wasm-simd-threaded.wasm');
  });
});
