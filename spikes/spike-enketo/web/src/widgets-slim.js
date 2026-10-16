// Size experiment (E1): survey-relevant widgets only; drops geo/leaflet, draw/signature, file, media, image-map.
import note from 'enketo-core/src/widget/note/notewidget';
import selectDesktop from 'enketo-core/src/widget/select-desktop/selectpicker';
import textarea from 'enketo-core/src/widget/textarea/textarea';
import table from 'enketo-core/src/widget/table/tablewidget';
import radio from 'enketo-core/src/widget/radio/radiopicker';
import dateNative from 'enketo-core/src/widget/date-native/datepicker-native';
import likert from 'enketo-core/src/widget/select-likert/likertitem';
import columns from 'enketo-core/src/widget/columns/columns';
import range from 'enketo-core/src/widget/range/range-widget';
import rank from 'enketo-core/src/widget/rank/rank-widget';
import textMax from 'enketo-core/src/widget/text-max/text-max';
import rating from 'enketo-core/src/widget/rating/rating';
import decimal from 'enketo-core/src/widget/number-input/decimal-input';
import integer from 'enketo-core/src/widget/number-input/integer-input';

export default [note, selectDesktop, textarea, table, radio, dateNative, likert, columns, range, rank, textMax, rating, decimal, integer];
