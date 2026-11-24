import Entity from "./base/entity.ts";

class Project extends Entity {
	get secondaryCard() {
		return this.elt.querySelector<HTMLElement>("#model-tasks");
	}
}

export default Project;
