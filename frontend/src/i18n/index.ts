import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './en.json';

await i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
  returnNull: false,
});

export default i18n;
