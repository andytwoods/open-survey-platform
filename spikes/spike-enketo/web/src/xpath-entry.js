// E5 harness page: expose Enketo's own XPath evaluator (openrosa-xpath-evaluator) to Playwright.
import OpenRosaXPath from 'openrosa-xpath-evaluator';
window.ORXE = OpenRosaXPath();
