import type { CurrentLocation } from './store';

const GEO_OPTIONS: PositionOptions = {
  enableHighAccuracy: false,
  timeout: 12000,
  maximumAge: 300000,
};

export function hasBrowserLocation(): boolean {
  return typeof navigator !== 'undefined' && 'geolocation' in navigator;
}

export function locationFromPosition(pos: GeolocationPosition): CurrentLocation {
  return {
    latitude: pos.coords.latitude,
    longitude: pos.coords.longitude,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Seoul',
  };
}

export function locationErrorMessage(err: GeolocationPositionError | unknown): string {
  if (!hasBrowserLocation()) return '위치 사용 불가';
  if (typeof err === 'object' && err && 'code' in err) {
    const code = (err as GeolocationPositionError).code;
    if (code === GeolocationPositionError.PERMISSION_DENIED) {
      return '위치 권한이 필요합니다';
    }
    if (code === GeolocationPositionError.POSITION_UNAVAILABLE) {
      return '위치를 가져올 수 없습니다';
    }
    if (code === GeolocationPositionError.TIMEOUT) {
      return '위치 확인 시간이 초과됐습니다';
    }
  }
  return '위치 확인에 실패했습니다';
}

export function requestCurrentLocation(): Promise<CurrentLocation> {
  if (!hasBrowserLocation()) {
    return Promise.reject(new Error('위치 사용 불가'));
  }
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve(locationFromPosition(pos)),
      reject,
      GEO_OPTIONS,
    );
  });
}

export function watchCurrentLocation(
  onLocation: (location: CurrentLocation) => void,
  onError: (message: string) => void,
): number | null {
  if (!hasBrowserLocation()) {
    onError('위치 사용 불가');
    return null;
  }
  return navigator.geolocation.watchPosition(
    (pos) => onLocation(locationFromPosition(pos)),
    (err) => onError(locationErrorMessage(err)),
    GEO_OPTIONS,
  );
}
