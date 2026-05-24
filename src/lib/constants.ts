/** FT Solutions branding & app defaults */
export const APP_NAME = "Fiverr Lead Extractor CRM";
export const COMPANY_NAME = "FT Solutions";
export const COMPANY_PHONE = "+923472543818";
export const ELECTRON_TITLE = `${APP_NAME} - ${COMPANY_NAME}`;

/** When true, hides dev commands and technical hints in the UI (client delivery). */
export const CLIENT_MODE =
  process.env.NEXT_PUBLIC_CLIENT_MODE === "true" ||
  process.env.NODE_ENV === "production";

export const DEFAULT_TARGET_COUNTRIES = ["United States", "Canada"];

export const TARGET_COUNTRY_OPTIONS = [
  "United States",
  "Canada",
  "United Kingdom",
  "Australia",
  "Germany",
  "India",
  "Pakistan",
  "France",
  "Netherlands",
  "Brazil",
];
