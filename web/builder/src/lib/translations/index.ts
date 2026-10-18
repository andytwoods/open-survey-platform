// The editing language of a survey page (planning/rich-text.md §5, task RT6).
export { default as EditingLanguageSelect } from './EditingLanguageSelect.svelte';
export { editingLanguage, editLanguageOf, initEditingLanguage, setEditingLanguage, setReferenceOpen } from './editing-language.svelte';
export { LANG_PARAM, langFromSearch, languageOptions, resolveEditingLanguage, withLang } from './editing-language';
