"use client";

import NextLink from "next/link";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  type ComponentProps,
  type ReactNode,
  type RefObject,
} from "react";

type NavigationVersion = RefObject<number>;
const NavigationContext = createContext<NavigationVersion | null>(null);

/** A pending navigation is intent even while Next retains the previous page. */
export function NavigationIntentProvider({
  children,
}: Readonly<{ children: ReactNode }>) {
  const versionRef = useRef(0);
  useEffect(() => {
    const onHistory = () => {
      versionRef.current += 1;
    };
    window.addEventListener("popstate", onHistory);
    return () => window.removeEventListener("popstate", onHistory);
  }, []);
  return (
    <NavigationContext.Provider value={versionRef}>
      {children}
    </NavigationContext.Provider>
  );
}

export function useNavigationVersionRef(): NavigationVersion {
  const shared = useContext(NavigationContext);
  const local = useRef(0);
  return shared ?? local;
}

/** Next invokes onNavigate only for a same-window client navigation. */
export default function NavigationLink({
  onNavigate,
  ...props
}: ComponentProps<typeof NextLink>) {
  const versionRef = useContext(NavigationContext);
  return (
    <NextLink
      {...props}
      onNavigate={(event) => {
        let prevented = false;
        onNavigate?.({
          preventDefault() {
            prevented = true;
            event.preventDefault();
          },
        });
        if (!prevented && versionRef) versionRef.current += 1;
      }}
    />
  );
}
