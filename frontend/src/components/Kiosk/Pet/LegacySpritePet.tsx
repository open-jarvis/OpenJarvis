import React from 'react';
import { CodexPet, type CodexPetProps } from './CodexPet';

export interface LegacySpritePetProps extends CodexPetProps {}

/**
 * LegacySpritePet wraps the existing 2D sprite/canvas pet implementation (Minty).
 * Serves as an isolated renderer for the 2D pet and a fallback target for PetRenderer.
 */
export const LegacySpritePet: React.FC<LegacySpritePetProps> = (props) => {
  return <CodexPet {...props} />;
};
