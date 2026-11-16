import { IMAGE_RULES } from '../../core/restaurant/restaurant.models';

/** Quick client-side check before uploading. Returns an error message, or null when acceptable. */
export function checkImageFile(file: File | null | undefined): string | null {
  if (!file) return 'No file selected.';
  if (!(IMAGE_RULES.types as readonly string[]).includes(file.type)) return 'Use a JPEG, PNG or WebP image.';
  if (file.size > IMAGE_RULES.maxBytes) return `The file is larger than ${IMAGE_RULES.maxBytes / 1024 / 1024} MB.`;
  return null;
}

/** Reads the first file from an <input type="file"> change event and clears the input for re-selection. */
export function takeFile(event: Event): File | null {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  input.value = '';
  return file;
}
