import Entity from "./base/entity.mjs";

class Project extends Entity {
	get secondaryCard() {
		return this.elt.querySelector("#model-tasks");
	}
}

export default Project;
