import { create } from "zustand";
import { PLATFORMS } from "../utils/constants";

export const usePlatformStore = create((set) => ({
  activePlatform: PLATFORMS.BLINKIT,
  setActivePlatform: (platform) => set({ activePlatform: platform }),
}));
