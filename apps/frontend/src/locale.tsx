import React from "react";
import { englishMessages, type LocaleMessages } from "./copy";

export const LocaleContext = React.createContext<{ text: LocaleMessages; locale: string }>({
  text: englishMessages,
  locale: "en-US"
});

export function useLocale() {
  return React.useContext(LocaleContext);
}
