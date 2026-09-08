// 导航与界面图标（内联 SVG，线性风格，对齐官网图标语义）
interface IconProps {
  className?: string;
}

export function StarIcon({ className = "size-4.5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M12 3l2.7 5.6 6.1.8-4.5 4.3 1.1 6.1L12 16.9 6.6 19.8l1.1-6.1L3.2 9.4l6.1-.8L12 3z" />
    </svg>
  );
}

export function ListIcon({ className = "size-4.5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
      <path d="M8 6h13M8 12h13M8 18h13" />
      <circle cx="4" cy="6" r="1" fill="currentColor" />
      <circle cx="4" cy="12" r="1" fill="currentColor" />
      <circle cx="4" cy="18" r="1" fill="currentColor" />
    </svg>
  );
}

export function FlameIcon({ className = "size-4.5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M12 21c3.9 0 6.5-2.6 6.5-6.2 0-2.5-1.3-4.4-2.6-6C14.7 7.3 13.5 5.8 13 3.5c-2.3 1.4-3.3 3.4-3.4 5.3-.9-.5-1.6-1.3-2-2.4-1.6 1.6-2.6 3.9-2.6 6C5 18.4 8.1 21 12 21z" />
    </svg>
  );
}

export function NewsIcon({ className = "size-4.5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3.5" y="5" width="17" height="15" rx="2" />
      <path d="M7.5 9.5h9M7.5 13h9M7.5 16.5h5" />
    </svg>
  );
}

export function SearchIcon({ className = "size-4" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </svg>
  );
}

/** 设置（sliders 线性风格，与导航图标一致） */
export function GearIcon({ className = "size-4.5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
      <path d="M4 7h9M19 7h1M4 17h5M14 17h6" />
      <circle cx="15.5" cy="7" r="2.2" />
      <circle cx="11.5" cy="17" r="2.2" />
    </svg>
  );
}

export function BookmarkIcon({ className = "size-4", filled = false }: IconProps & { filled?: boolean }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M6.5 4.5h11a1 1 0 0 1 1 1V21l-6.5-3.8L5.5 21V5.5a1 1 0 0 1 1-1z" />
    </svg>
  );
}

export function ArrowRightIcon({ className = "size-3.5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M4 12h16m-6-6 6 6-6 6" />
    </svg>
  );
}

export function MenuIcon({ className = "size-5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}

export function CloseIcon({ className = "size-5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

/** 品牌 Logo：深青圆底 + 白色火焰 */
export function BrandLogo({ className = "size-9" }: IconProps) {
  return (
    <span
      className={`${className} inline-flex items-center justify-center rounded-full bg-gradient-to-br from-brand to-brand-strong text-white`}
      aria-hidden
    >
      <FlameIcon className="size-4.5" />
    </span>
  );
}
