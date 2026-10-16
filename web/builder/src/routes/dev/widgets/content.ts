// Sample question text for the widget gallery: English, long German labels, and Arabic (RTL).
// Made-up wording only; no real participant data.
import type { Choice, Text, WidgetMessages } from '@osp/ui-components/survey';

export type Variant = 'en' | 'de' | 'ar';

export interface GalleryContent {
	lang: string;
	title: string;
	states: { empty: string; answered: string; error: string; disabled: string };
	required: string;
	messages?: Partial<WidgetMessages>;
	integer: { label: Text; help: Text };
	decimal: { label: Text; help: Text };
	text: { label: Text; help: Text; answer: string };
	long: { label: Text; help: Text; answer: string };
	single: { label: Text; help: Text; choices: Choice[] };
	multi: { label: Text; help: Text; choices: Choice[] };
	date: { label: Text; help: Text };
	note: { label: Text; help: Text };
	matrix: { label: Text; help: Text; rows: Choice[]; choices: Choice[] };
	slider: { label: Text; help: Text; minLabel: Text; maxLabel: Text };
	reveal: { button: string; label: Text };
}

const en: GalleryContent = {
	lang: 'en-GB',
	title: 'Question widgets',
	states: { empty: 'Empty', answered: 'Answered', error: 'Error', disabled: 'Disabled' },
	required: 'This question needs an answer.',
	integer: { label: 'How old are you?', help: 'In whole years.' },
	decimal: { label: 'What is your weight in kilograms?', help: 'Decimals are fine.' },
	text: { label: 'What is your first name?', help: 'As you would like to be addressed.', answer: 'Alex' },
	long: {
		label: [{ text: 'Is there ' }, { text: 'anything else', strong: true }, { text: ' you would like to tell us?' }],
		help: 'The box grows as you type.',
		answer: 'The survey was clear.\nThe second page was a little long.'
	},
	single: {
		label: 'Which fruit do you eat most often?',
		help: 'Choose one.',
		choices: [
			{ value: 'apple', label: 'Apple' },
			{ value: 'pear', label: 'Pear' },
			{ value: 'plum', label: 'Plum', help: 'Fresh or dried' },
			{ value: 'none', label: 'None of these' }
		]
	},
	multi: {
		label: 'Which of these do you use?',
		help: 'Choose all that apply.',
		choices: [
			{ value: 'bike', label: 'Bicycle' },
			{ value: 'bus', label: 'Bus' },
			{ value: 'car', label: 'Car' },
			{ value: 'train', label: 'Train' }
		]
	},
	date: { label: 'What is your date of birth?', help: 'For example, 27 3 1990.' },
	note: {
		label: [{ text: 'Thank you. ' }, { text: 'The next questions are about your daily routine.', em: true }],
		help: 'There are no right or wrong answers.'
	},
	matrix: {
		label: 'How much do you agree with each statement?',
		help: 'One answer per row.',
		rows: [
			{ value: 'easy', label: 'The app is easy to use' },
			{ value: 'recommend', label: 'I would recommend it to a friend' },
			{ value: 'again', label: 'I would use it again' }
		],
		choices: [
			{ value: '1', label: 'Strongly disagree' },
			{ value: '2', label: 'Disagree' },
			{ value: '3', label: 'Neutral' },
			{ value: '4', label: 'Agree' },
			{ value: '5', label: 'Strongly agree' }
		]
	},
	slider: {
		label: 'How bad is your pain right now?',
		help: 'Drag, tap the line, or use the arrow keys.',
		minLabel: 'No pain',
		maxLabel: 'Worst pain imaginable'
	},
	reveal: { button: 'Show the follow-up question', label: 'Which other fruit do you eat?' }
};

const de: GalleryContent = {
	lang: 'de',
	title: 'Fragebausteine für Teilnehmende',
	states: { empty: 'Leer', answered: 'Beantwortet', error: 'Fehler', disabled: 'Deaktiviert' },
	required: 'Bitte beantworten Sie diese Frage, bevor Sie fortfahren.',
	messages: {
		required: 'Pflichtfeld',
		day: 'Tag',
		month: 'Monat',
		year: 'Jahr',
		notAnswered: 'Nicht beantwortet',
		sliderValue: 'Wert',
		sliderTypeValue: 'Oder geben Sie eine Zahl ein',
		invalidInteger: 'Geben Sie eine ganze Zahl ein, z. B. 12.',
		invalidDecimal: 'Geben Sie eine Zahl ein, z. B. {example}.',
		outOfRange: 'Geben Sie eine Zahl von {min} bis {max} ein.',
		incompleteDate: 'Geben Sie Tag, Monat und Jahr ein.',
		invalidDate: 'Geben Sie ein gültiges Datum ein.',
		revealed: 'Neue Frage: {label}'
	},
	integer: {
		label: 'Wie alt sind Sie zum Zeitpunkt dieser Befragung in vollendeten Lebensjahren?',
		help: 'Bitte nur ganze Lebensjahre angeben.'
	},
	decimal: {
		label: 'Wie hoch ist Ihr aktuelles Körpergewicht in Kilogramm?',
		help: 'Nachkommastellen mit Komma, zum Beispiel 72,5.'
	},
	text: {
		label: 'Bitte geben Sie Ihren Vornamen so an, wie Sie angesprochen werden möchten',
		help: 'Ihre Angabe wird ausschließlich für diese Befragung verwendet.',
		answer: 'Maximiliane'
	},
	long: {
		label: 'Möchten Sie uns abschließend noch weitere Anmerkungen, Verbesserungsvorschläge oder Rückmeldungen mitteilen?',
		help: 'Das Eingabefeld wächst mit Ihrem Text.',
		answer: 'Die Befragung war verständlich.\nDie zweite Seite war etwas lang.'
	},
	single: {
		label: 'Welche Versicherung haben Sie in den letzten zwölf Monaten am häufigsten in Anspruch genommen?',
		help: 'Bitte wählen Sie genau eine Antwort aus.',
		choices: [
			{ value: 'rs', label: 'Rechtsschutzversicherungsgesellschaft' },
			{ value: 'kfz', label: 'Kraftfahrzeughaftpflichtversicherung' },
			{ value: 'hr', label: 'Hausratversicherung', help: 'Einschließlich Glasbruchversicherung' },
			{ value: 'keine', label: 'Keine der genannten Versicherungen' }
		]
	},
	multi: {
		label: 'Welche der folgenden Verkehrsmittel nutzen Sie regelmäßig für den Arbeitsweg?',
		help: 'Mehrfachnennungen sind möglich.',
		choices: [
			{ value: 'bike', label: 'Fahrrad oder Elektrofahrrad' },
			{ value: 'bus', label: 'Öffentlicher Personennahverkehr' },
			{ value: 'car', label: 'Personenkraftwagen' },
			{ value: 'train', label: 'Regionalexpress oder Fernverkehrszug' }
		]
	},
	date: { label: 'Wann sind Sie geboren?', help: 'Zum Beispiel 27 3 1990.' },
	note: {
		label: 'Vielen Dank. Die folgenden Fragen beziehen sich auf Ihren Arbeitsalltag und Ihre Freizeitgestaltung.',
		help: 'Es gibt keine richtigen oder falschen Antworten.'
	},
	matrix: {
		label: 'Inwieweit stimmen Sie den folgenden Aussagen zu?',
		help: 'Eine Antwort pro Zeile.',
		rows: [
			{ value: 'easy', label: 'Die Benutzeroberfläche der Anwendung ist übersichtlich und leicht verständlich' },
			{ value: 'recommend', label: 'Ich würde diese Anwendung meinen Kolleginnen und Kollegen weiterempfehlen' },
			{ value: 'again', label: 'Ich würde die Anwendung wieder verwenden' }
		],
		choices: [
			{ value: '1', label: 'Stimme überhaupt nicht zu' },
			{ value: '2', label: 'Stimme eher nicht zu' },
			{ value: '3', label: 'Weder noch' },
			{ value: '4', label: 'Stimme eher zu' },
			{ value: '5', label: 'Stimme voll und ganz zu' }
		]
	},
	slider: {
		label: 'Wie stark sind Ihre Schmerzen im Moment?',
		help: 'Ziehen, auf die Linie tippen oder die Pfeiltasten verwenden.',
		minLabel: 'Keine Schmerzen',
		maxLabel: 'Stärkste vorstellbare Schmerzen'
	},
	reveal: { button: 'Folgefrage anzeigen', label: 'Welche weitere Versicherung haben Sie?' }
};

const ar: GalleryContent = {
	lang: 'ar',
	title: 'عناصر الأسئلة',
	states: { empty: 'فارغ', answered: 'تمت الإجابة', error: 'خطأ', disabled: 'معطّل' },
	required: 'هذا السؤال مطلوب.',
	messages: {
		required: 'مطلوب',
		day: 'اليوم',
		month: 'الشهر',
		year: 'السنة',
		notAnswered: 'لم تتم الإجابة',
		sliderValue: 'القيمة',
		sliderTypeValue: 'أو اكتب رقماً',
		invalidInteger: 'أدخل عدداً صحيحاً، مثل 12.',
		invalidDecimal: 'أدخل رقماً، مثل {example}.',
		outOfRange: 'أدخل رقماً من {min} إلى {max}.',
		incompleteDate: 'أدخل اليوم والشهر والسنة.',
		invalidDate: 'أدخل تاريخاً صحيحاً.',
		revealed: 'سؤال جديد: {label}'
	},
	integer: { label: 'كم عمرك؟', help: 'بالسنوات الكاملة.' },
	decimal: { label: 'ما وزنك بالكيلوغرام؟', help: 'يمكنك استخدام الكسور العشرية.' },
	text: { label: 'ما اسمك الأول؟', help: 'كما تحب أن تتم مناداتك.', answer: 'سارة' },
	long: {
		label: 'هل لديك أي تعليقات أخرى تود مشاركتها معنا؟',
		help: 'يتسع الحقل كلما كتبت.',
		answer: 'كان الاستبيان واضحاً.\nكانت الصفحة الثانية طويلة قليلاً.'
	},
	single: {
		label: 'ما الفاكهة التي تأكلها أكثر من غيرها؟',
		help: 'اختر إجابة واحدة.',
		choices: [
			{ value: 'apple', label: 'تفاح' },
			{ value: 'pear', label: 'كمثرى' },
			{ value: 'plum', label: 'برقوق', help: 'طازج أو مجفف' },
			{ value: 'none', label: 'لا شيء مما سبق' }
		]
	},
	multi: {
		label: 'أي من وسائل النقل هذه تستخدم؟',
		help: 'اختر كل ما ينطبق.',
		choices: [
			{ value: 'bike', label: 'دراجة' },
			{ value: 'bus', label: 'حافلة' },
			{ value: 'car', label: 'سيارة' },
			{ value: 'train', label: 'قطار' }
		]
	},
	date: { label: 'ما تاريخ ميلادك؟', help: 'مثال: 27 3 1990.' },
	note: { label: 'شكراً لك. الأسئلة التالية عن روتينك اليومي.', help: 'لا توجد إجابات صحيحة أو خاطئة.' },
	matrix: {
		label: 'إلى أي مدى توافق على كل عبارة؟',
		help: 'إجابة واحدة لكل صف.',
		rows: [
			{ value: 'easy', label: 'التطبيق سهل الاستخدام' },
			{ value: 'recommend', label: 'سأوصي به لصديق' },
			{ value: 'again', label: 'سأستخدمه مرة أخرى' }
		],
		choices: [
			{ value: '1', label: 'لا أوافق بشدة' },
			{ value: '2', label: 'لا أوافق' },
			{ value: '3', label: 'محايد' },
			{ value: '4', label: 'أوافق' },
			{ value: '5', label: 'أوافق بشدة' }
		]
	},
	slider: {
		label: 'ما مدى شدة ألمك الآن؟',
		help: 'اسحب أو انقر على الخط أو استخدم مفاتيح الأسهم.',
		minLabel: 'لا ألم',
		maxLabel: 'أسوأ ألم يمكن تخيله'
	},
	reveal: { button: 'أظهر سؤال المتابعة', label: 'ما الفاكهة الأخرى التي تأكلها؟' }
};

export const variants: Record<Variant, GalleryContent> = { en, de, ar };

export function variantFrom(param: string | null): Variant {
	return param === 'de' || param === 'ar' ? param : 'en';
}
