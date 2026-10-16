// Our app-level Enketo config (replaces enketo-core's `enketo/config` via the build alias).
// excludeNonRelevant is switchable per page load so the spike can compare both modes (E8).
export default {
    experimentalOptimizations: { computeAsync: false },
    excludeNonRelevant: Boolean(window.__SPIKE__ && window.__SPIKE__.excludeNonRelevant),
    maps: [],
    googleApiKey: '',
    repeatOrdinals: false,
    validateContinuously: false,
    validatePage: true,
    swipePage: false,
    textMaxChars: 2000,
};
