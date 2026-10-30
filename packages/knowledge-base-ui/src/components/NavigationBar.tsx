import { Link } from '@tanstack/react-router';

import { ModeToggle } from '@/components/mode-toggle';
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from '@/components/ui/navigation-menu';
import { kindTitle } from '@/lib/kinds';

const linkClass = 'font-semibold hover:rounded-md';
const activeProps = { 'data-active': true };

export function NavigationBar({ kinds }: Readonly<{ kinds: readonly string[] }>) {
  return (
    <header className="flex items-center justify-between border-b p-1">
      <NavigationMenu viewport={false}>
        <NavigationMenuList>
          {kinds.map((kind) => (
            <NavigationMenuItem key={kind}>
              <NavigationMenuLink asChild className={linkClass}>
                <Link to="/$kind" params={{ kind }} activeProps={activeProps}>
                  {kindTitle(kind)}
                </Link>
              </NavigationMenuLink>
            </NavigationMenuItem>
          ))}
          <NavigationMenuItem>
            <NavigationMenuLink asChild className={linkClass}>
              <Link to="/search" activeProps={activeProps}>
                Search
              </Link>
            </NavigationMenuLink>
          </NavigationMenuItem>
          <NavigationMenuItem>
            <NavigationMenuLink asChild className={linkClass}>
              <Link to="/admin" activeProps={activeProps}>
                Admin
              </Link>
            </NavigationMenuLink>
          </NavigationMenuItem>
        </NavigationMenuList>
      </NavigationMenu>
      <ModeToggle />
    </header>
  );
}
