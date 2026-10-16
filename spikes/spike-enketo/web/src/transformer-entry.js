// E2 alternative: enketo-transformer's browser build (uses the browser's XSLTProcessor).
import { transform, version } from 'enketo-transformer/web';
window.enketoTransform = { transform, version };
