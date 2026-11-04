// Deliberately memory-only: a reload or tab close requires signing in again.
let accessToken = ''
let generation = 0
export const ACCESS_ENDED = 'sentinel-access-ended'

export function setAccessToken(value: string) {
  accessToken = value
  generation++
}

export function accessSnapshot() {
  return { token: accessToken, generation }
}

export function endAccess(expectedGeneration?: number) {
  if (expectedGeneration !== undefined && expectedGeneration !== generation) return
  setAccessToken('')
  window.dispatchEvent(new Event(ACCESS_ENDED))
}
