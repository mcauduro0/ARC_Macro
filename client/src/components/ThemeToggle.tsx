/**
 * ThemeToggle — Dark/Light mode toggle button
 * Animated sun/moon icon with smooth transition
 */

import { motion } from 'framer-motion';
import { Sun, Moon } from 'lucide-react';
import { useTheme } from '@/contexts/ThemeContext';

interface Props {
  size?: 'sm' | 'md';
  className?: string;
}

export function ThemeToggle({ size = 'sm', className = '' }: Props) {
  const { theme, toggleTheme, switchable } = useTheme();

  if (!switchable || !toggleTheme) return null;

  const isDark = theme === 'dark';
  const iconSize = size === 'sm' ? 'w-4 h-4' : 'w-5 h-5';
  const buttonSize = size === 'sm' ? 'w-8 h-8' : 'w-10 h-10';

  return (
    <button
      onClick={toggleTheme}
      className={`${buttonSize} flex items-center justify-center rounded-lg bg-muted/20 hover:bg-muted/40 active:bg-muted/60 transition-colors ${className}`}
      aria-label={isDark ? 'Mudar para modo claro' : 'Mudar para modo escuro'}
      title={isDark ? 'Modo Claro' : 'Modo Escuro'}
    >
      <motion.div
        key={theme}
        initial={{ scale: 0, rotate: -90 }}
        animate={{ scale: 1, rotate: 0 }}
        exit={{ scale: 0, rotate: 90 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        {isDark ? (
          <Sun className={`${iconSize} text-amber-400`} />
        ) : (
          <Moon className={`${iconSize} text-primary`} />
        )}
      </motion.div>
    </button>
  );
}
