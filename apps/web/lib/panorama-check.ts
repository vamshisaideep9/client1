// Browser-side pre-check for 360 images, mirroring the API's equirectangular
// rule (services/media_processing.py: 2:1 within 2%, at least 1024 x 512, at
// most 25 megapixels). It only saves a wasted upload; the API stays the gate.

export const PANORAMA_MIN_WIDTH = 1024;
export const PANORAMA_MIN_HEIGHT = 512;
const PANORAMA_MAX_PIXELS = 25_000_000;

/** Why an image of this size is not a usable 360 panorama, or null when it is. */
export function panoramaShapeError(name: string, width: number, height: number): string | null {
  const size = `${width} × ${height}`;
  if (width < PANORAMA_MIN_WIDTH || height < PANORAMA_MIN_HEIGHT) {
    return `${name} is ${size}. A 360 image must be at least ${PANORAMA_MIN_WIDTH} × ${PANORAMA_MIN_HEIGHT} pixels.`;
  }
  if (Math.abs(width - height * 2) > Math.max(2, Math.floor(height / 50))) {
    return `${name} is ${size}. A 360 image must be twice as wide as it is tall (2:1).`;
  }
  if (width * height > PANORAMA_MAX_PIXELS) {
    return `${name} is ${size}. A 360 image can be at most 25 megapixels.`;
  }
  return null;
}

/**
 * Read each file's pixel size and report the first problem. Files the browser
 * cannot decode are left to the API, which re-checks every upload.
 */
export async function firstPanoramaError(files: readonly File[]): Promise<string | null> {
  for (const file of files) {
    let width: number;
    let height: number;
    try {
      const bitmap = await createImageBitmap(file);
      width = bitmap.width;
      height = bitmap.height;
      bitmap.close();
    } catch {
      continue;
    }
    const error = panoramaShapeError(file.name, width, height);
    if (error) return error;
  }
  return null;
}
