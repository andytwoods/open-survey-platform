// Schema-driven property panel (task B4, builder-design §2).
export { default as PropertyPanel } from './PropertyPanel.svelte';
export { default as PropertyField } from './PropertyField.svelte';
export { default as BufferedInput } from './BufferedInput.svelte';
export {
	EDITOR_KINDS,
	EXTERNAL_KINDS,
	TEXT_DEBOUNCE_MS,
	diagnosticsFor,
	groupProperties,
	opAddress,
	propertyPointer,
	setPropertyOp,
	withTranslation
} from './logic';
export * from './types';
