import { RouterProvider } from "react-router-dom";
import { Providers } from "./app/providers";
import { router } from "./app/router";

/** Root: global providers wrapping the router. Wiring only — no UI lives here. */
const App = () => {
	return (
		<Providers>
			<RouterProvider router={router} />
		</Providers>
	);
};

export default App;
